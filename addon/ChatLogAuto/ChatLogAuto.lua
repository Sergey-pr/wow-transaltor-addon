-- Chat logging is what feeds the external translator: the client appends every
-- chat line to Logs/WoWChatLog.txt while it is on. It resets to off on every
-- login, so this addon just turns it back on and says so.

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")

local function Say(msg)
    DEFAULT_CHAT_FRAME:AddMessage("|cff33ff99ChatLogAuto:|r " .. msg)
end

local function Apply()
    if ChatLogAutoDB.enabled then
        LoggingChat(true)
    else
        LoggingChat(false)
    end
end

frame:SetScript("OnEvent", function()
    ChatLogAutoDB = ChatLogAutoDB or { enabled = true, quiet = false }
    if ChatLogAutoDB.enabled == nil then ChatLogAutoDB.enabled = true end

    Apply()

    if not ChatLogAutoDB.quiet then
        if ChatLogAutoDB.enabled then
            Say("chat logging is |cff00ff00on|r. Type /cla off to disable, /cla quiet to hide this message.")
        else
            Say("chat logging is |cffff0000off|r. Type /cla on to enable.")
        end
    end
end)

SLASH_CHATLOGAUTO1 = "/cla"
SLASH_CHATLOGAUTO2 = "/chatlogauto"

SlashCmdList["CHATLOGAUTO"] = function(arg)
    arg = string.lower(string.trim(arg or ""))

    if arg == "on" then
        ChatLogAutoDB.enabled = true
        Apply()
        Say("chat logging |cff00ff00on|r.")
    elseif arg == "off" then
        ChatLogAutoDB.enabled = false
        Apply()
        Say("chat logging |cffff0000off|r.")
    elseif arg == "quiet" then
        ChatLogAutoDB.quiet = not ChatLogAutoDB.quiet
        Say(ChatLogAutoDB.quiet and "login message hidden." or "login message shown.")
    else
        Say("/cla on | off | quiet  -- currently " ..
            (ChatLogAutoDB.enabled and "|cff00ff00on|r" or "|cffff0000off|r"))
    end
end
