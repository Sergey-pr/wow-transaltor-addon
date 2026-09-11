-- Pushes chat out of the client the only way the sandbox allows: by drawing it.
--
-- The client buffers Logs/WoWChatLog.txt in blocks of tens of kilobytes, so a
-- line can sit unwritten for minutes on a quiet realm. Addons have no sockets
-- and no file writes, but they can colour pixels, and another process can read
-- those pixels back off the screen. That is this file.
--
-- A grid of cells carries one message at a time. Each cell is a six-bit symbol:
-- two bits per colour channel, four levels apart, so the reader can snap a
-- drifted colour back to the nearest level instead of failing.

local COLS, ROWS = 44, 12
local HEADER_CELLS = 9          -- 6 magic + 1 sequence + 2 length
local PAYLOAD_CELLS = COLS * ROWS - HEADER_CELLS
local CELL_PIXELS = 3           -- screen pixels per cell, square
local HOLD = 0.10               -- seconds a message stays up, so a reader
                                -- sampling faster than this cannot miss it
local SEPARATOR = "\031"        -- between channel, sender and text

-- Two bits per channel. The reader snaps to the nearest of these.
local LEVEL = { [0] = 0, 85 / 255, 170 / 255, 1 }

-- White, red, green, blue, dark grey, light grey: the pattern the reader hunts
-- for. Six cells rather than three, because a shorter marker draws false
-- matches out of ordinary screen content and the reader then locks onto the
-- wrong place and never sees a message.
local MAGIC = { 63, 48, 12, 3, 21, 42 }

local EVENTS = {
    "CHAT_MSG_SAY", "CHAT_MSG_YELL", "CHAT_MSG_GUILD", "CHAT_MSG_OFFICER",
    "CHAT_MSG_PARTY", "CHAT_MSG_PARTY_LEADER", "CHAT_MSG_RAID",
    "CHAT_MSG_RAID_LEADER", "CHAT_MSG_WHISPER", "CHAT_MSG_WHISPER_INFORM",
    "CHAT_MSG_CHANNEL", "CHAT_MSG_EMOTE",
}

-- Event name -> the channel label the overlay shows.
local LABEL = {
    CHAT_MSG_SAY = "Say", CHAT_MSG_YELL = "Yell", CHAT_MSG_GUILD = "Guild",
    CHAT_MSG_OFFICER = "Officer", CHAT_MSG_PARTY = "Party",
    CHAT_MSG_PARTY_LEADER = "Party", CHAT_MSG_RAID = "Raid",
    CHAT_MSG_RAID_LEADER = "Raid", CHAT_MSG_WHISPER = "Whisper",
    CHAT_MSG_WHISPER_INFORM = "Whisper to", CHAT_MSG_EMOTE = "Emote",
}

-- The fixed labels, in the order the listing shows them. Numbered channels
-- like Trade are discovered at runtime instead.
local FIXED = { "Say", "Yell", "Emote", "Guild", "Officer", "Party", "Raid",
                "Whisper", "Whisper to" }

local queue = {}
local cells = {}
local sequence = 0
local holding = 0
local frame

-- ---------------------------------------------------------------- filtering

-- ChatPixelBridgeDB.channels is nil while everything is allowed through. Once
-- a filter is chosen it maps a lowercased name to the name as typed, so the
-- listing can print "LookingForGroup" rather than the folded-down key.
--
-- Filtering here rather than in the overlay keeps the strip free for lines
-- that matter: it carries about ten messages a second, and a busy Trade alone
-- can beat that.

local function allowed(label)
    local wanted = ChatPixelBridgeDB.channels
    return wanted == nil or wanted[string.lower(label)] ~= nil
end

local function joined_channels()
    local names = {}
    local list = { GetChannelList() }
    -- GetChannelList returns id, name, disabled repeating.
    for i = 2, #list, 3 do
        if type(list[i]) == "string" and list[i] ~= "" then
            names[#names + 1] = list[i]
        end
    end
    return names
end

local function known_labels()
    local labels, seen = {}, {}
    for _, name in ipairs(FIXED) do
        labels[#labels + 1] = name
        seen[string.lower(name)] = true
    end
    for _, name in ipairs(joined_channels()) do
        if not seen[string.lower(name)] then
            labels[#labels + 1] = name
            seen[string.lower(name)] = true
        end
    end
    -- Anything already chosen but not currently joined still belongs on screen.
    if ChatPixelBridgeDB.channels then
        for key, display in pairs(ChatPixelBridgeDB.channels) do
            if not seen[key] then
                -- Older saves stored `true` here rather than the typed name.
                labels[#labels + 1] = type(display) == "string" and display or key
                seen[key] = true
            end
        end
    end
    return labels
end

-- ------------------------------------------------------------------ encoding

-- Bytes in, six-bit symbols out. Plain arithmetic: the bit library has moved
-- around between client versions, this has not.
local function to_symbols(text)
    local out, acc, bits = {}, 0, 0
    for i = 1, #text do
        acc = acc * 256 + string.byte(text, i)
        bits = bits + 8
        while bits >= 6 do
            bits = bits - 6
            local divisor = 2 ^ bits
            out[#out + 1] = math.floor(acc / divisor) % 64
            acc = acc % divisor
        end
    end
    if bits > 0 then                        -- pad the tail out to a full symbol
        out[#out + 1] = (acc * 2 ^ (6 - bits)) % 64
    end
    return out
end

local function paint(index, symbol)
    local texture = cells[index]
    if not texture then return end
    local r = LEVEL[math.floor(symbol / 16) % 4]
    local g = LEVEL[math.floor(symbol / 4) % 4]
    local b = LEVEL[symbol % 4]
    -- SetColorTexture is the modern name; older clients only have the
    -- colour form of SetTexture.
    if texture.SetColorTexture then
        texture:SetColorTexture(r, g, b, 1)
    else
        texture:SetTexture(r, g, b, 1)
    end
end

-- The marker stays lit even with nothing to send: it is what the reader hunts
-- for, and it has to be findable before the first message ever arrives.
local function blank()
    for i = 1, COLS * ROWS do
        paint(i, 0)
    end
    for i = 1, #MAGIC do
        paint(i, MAGIC[i])
    end
end

local function show(payload)
    local symbols = to_symbols(payload)
    local count = math.min(#symbols, PAYLOAD_CELLS)

    sequence = (sequence + 1) % 64
    for i = 1, #MAGIC do
        paint(i, MAGIC[i])
    end
    paint(#MAGIC + 1, sequence)
    paint(#MAGIC + 2, math.floor(count / 64) % 64)  -- length, high six bits
    paint(#MAGIC + 3, count % 64)                   -- length, low six bits

    for i = 1, PAYLOAD_CELLS do
        paint(HEADER_CELLS + i, i <= count and symbols[i] or 0)
    end
end

-- --------------------------------------------------------------------- frame

local function build()
    frame = CreateFrame("Frame", "ChatPixelBridgeFrame", UIParent)
    frame:SetFrameStrata("TOOLTIP")         -- above the rest of the UI
    frame:SetToplevel(true)

    -- UI units are not screen pixels: the UI is always 768 units tall, whatever
    -- the resolution. One screen pixel is UIParent's height over the physical
    -- height. Getting this wrong makes cells a fractional number of pixels.
    local pixel
    if GetPhysicalScreenSize then
        local _, physical = GetPhysicalScreenSize()
        pixel = UIParent:GetHeight() / physical
    else
        pixel = 1 / UIParent:GetEffectiveScale()
    end
    local cell = CELL_PIXELS * pixel

    frame:SetSize(cell * COLS, cell * ROWS)
    frame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)

    for row = 0, ROWS - 1 do
        for col = 0, COLS - 1 do
            local texture = frame:CreateTexture(nil, "OVERLAY")
            texture:SetSize(cell, cell)
            texture:SetPoint("TOPLEFT", frame, "TOPLEFT", col * cell, -row * cell)
            cells[row * COLS + col + 1] = texture
        end
    end
    blank()
end

local function Say(message)
    DEFAULT_CHAT_FRAME:AddMessage("|cff33ff99ChatPixelBridge:|r " .. message)
end

-- ------------------------------------------------------------------- driving

-- After a quiet spell the message body is hidden. The header stays: it is only
-- 27x3 pixels, and it is what the reader locates the strip by, so hiding it
-- would lose the first message after every pause while the reader searched.
local IDLE_AFTER = 5
local idle = 0
local body_shown = true

local function set_body(visible)
    if visible == body_shown then return end
    body_shown = visible
    for i = HEADER_CELLS + 1, COLS * ROWS do
        if visible then cells[i]:Show() else cells[i]:Hide() end
    end
end

local function OnUpdate(_self, elapsed)
    holding = holding - elapsed
    if holding > 0 then return end

    local next_message = table.remove(queue, 1)
    if next_message then
        set_body(true)
        show(next_message)
        holding = HOLD
        idle = 0
    else
        idle = idle + elapsed
        if idle >= IDLE_AFTER then
            set_body(false)
        end
    end
end

local function OnChat(event, text, sender, _language, channelName)
    if not ChatPixelBridgeDB.enabled or not text or text == "" then return end

    local label = LABEL[event]
    if event == "CHAT_MSG_CHANNEL" then
        -- "2. Trade - Orgrimmar" -> "Trade", matching the log's own naming.
        label = tostring(channelName or "Channel")
        label = label:gsub("^%d+%.%s*", ""):gsub(" %- .*$", "")
    end
    label = label or "Chat"

    if not allowed(label) then return end

    sender = tostring(sender or "?"):gsub("%-.*$", "")
    -- Drop the client's own hyperlink markup; the overlay would only strip it.
    text = text:gsub("|H.-|h(.-)|h", "%1"):gsub("|c%x%x%x%x%x%x%x%x", "")
               :gsub("|r", ""):gsub("|T.-|t", "")

    if #queue < 200 then        -- a burst is worth queueing, a flood is not
        queue[#queue + 1] = label .. SEPARATOR .. sender .. SEPARATOR .. text
    end
end

-- --------------------------------------------------------------------- setup

local driver = CreateFrame("Frame")
driver:RegisterEvent("PLAYER_LOGIN")
for _, event in ipairs(EVENTS) do
    driver:RegisterEvent(event)
end

driver:SetScript("OnEvent", function(_self, event, ...)
    if event == "PLAYER_LOGIN" then
        ChatPixelBridgeDB = ChatPixelBridgeDB or {}
        if ChatPixelBridgeDB.enabled == nil then ChatPixelBridgeDB.enabled = true end

        build()
        frame:SetScript("OnUpdate", OnUpdate)
        frame:SetShown(ChatPixelBridgeDB.enabled)

        if not ChatPixelBridgeDB.quiet then
            Say(ChatPixelBridgeDB.enabled
                and "on. The strip in the top-left corner is the data channel — "
                    .. "leave it uncovered. /cpb off to hide it."
                or "off. /cpb on to enable.")
        end
    else
        OnChat(event, ...)
    end
end)

SLASH_CHATPIXELBRIDGE1 = "/cpb"

local function ShowChannels()
    Say(ChatPixelBridgeDB.channels and "sending these channels:"
                                    or "sending |cff00ff00every|r channel:")
    for _, label in ipairs(known_labels()) do
        local on = allowed(label)
        DEFAULT_CHAT_FRAME:AddMessage(string.format(
            "   %s %s|r", on and "|cff00ff00[x]" or "|cff808080[ ]",
            (on and "|cffffffff" or "|cff808080") .. label))
    end
    Say("/cpb add <name> | drop <name> | only <a> <b> ... | all")
end

-- A channel name can carry pattern-magic characters, so anything spliced into
-- a pattern has to be escaped first.
local function escape(text)
    return (string.gsub(text, "([%^%$%(%)%%%.%[%]%*%+%-%?])", "%%%1"))
end

-- Splits "guild whisper" on spaces but keeps quoted names whole, so a channel
-- with a space in it can still be named.
local function words(text)
    local out = {}
    for piece in string.gmatch(text, '"([^"]+)"') do
        out[#out + 1] = piece
        text = string.gsub(text, '"' .. escape(piece) .. '"', "", 1)
    end
    for piece in string.gmatch(text, "%S+") do
        out[#out + 1] = piece
    end
    return out
end

SlashCmdList["CHATPIXELBRIDGE"] = function(argument)
    argument = strtrim(argument or "")
    local command, rest = string.match(argument, "^(%S*)%s*(.*)$")
    command = string.lower(command or "")

    if command == "on" or command == "off" then
        ChatPixelBridgeDB.enabled = command == "on"
        if frame then frame:SetShown(ChatPixelBridgeDB.enabled) end
        Say(command == "on" and "on." or "off.")

    elseif command == "quiet" then
        ChatPixelBridgeDB.quiet = not ChatPixelBridgeDB.quiet
        Say(ChatPixelBridgeDB.quiet and "login message hidden."
                                     or "login message shown.")

    elseif command == "test" then
        -- Straight onto the queue, past the channel filter: a test that a
        -- filter can swallow tells you nothing about the link.
        queue[#queue + 1] = "Bridge test" .. SEPARATOR .. UnitName("player") ..
                            SEPARATOR .. "pixel bridge test " .. math.random(1000, 9999)
        Say("queued a test line.")

    elseif command == "channels" or command == "list" then
        ShowChannels()

    elseif command == "all" then
        ChatPixelBridgeDB.channels = nil
        Say("sending every channel.")

    elseif command == "only" then
        local names = words(rest)
        if #names == 0 then
            Say("name at least one channel, or use /cpb all.")
            return
        end
        ChatPixelBridgeDB.channels = {}
        for _, name in ipairs(names) do
            ChatPixelBridgeDB.channels[string.lower(name)] = name
        end
        Say("sending only: " .. table.concat(names, ", "))

    elseif command == "add" or command == "drop" then
        local names = words(rest)
        if #names == 0 then
            Say("name a channel, e.g. /cpb " .. command .. " Trade")
            return
        end
        if ChatPixelBridgeDB.channels == nil then
            -- Was unfiltered: start from everything on, so `drop` removes one
            -- rather than silently turning all the others off.
            ChatPixelBridgeDB.channels = {}
            for _, label in ipairs(known_labels()) do
                ChatPixelBridgeDB.channels[string.lower(label)] = label
            end
        end
        for _, name in ipairs(names) do
            ChatPixelBridgeDB.channels[string.lower(name)] =
                command == "add" and name or nil
        end
        Say((command == "add" and "added: " or "dropped: ")
            .. table.concat(names, ", "))

    else
        Say("/cpb on | off | quiet | test | channels | add | drop | only | all")
        Say("currently " .. (ChatPixelBridgeDB.enabled and "|cff00ff00on|r"
                                                        or "|cffff0000off|r"))
    end
end
