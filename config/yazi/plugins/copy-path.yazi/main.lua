--- @sync entry
return {
  entry = function()
    local h = cx.active.current.hovered

    if not h then
      ya.notify({ title = "Error", content = "No file selected" })
      return
    end

    local path = tostring(h.url)

    -- Check if we're in SSH session
    local ssh_connection = os.getenv("SSH_CONNECTION")

    if ssh_connection then
      -- SSH: Use OSC 52 with ANSI-C quoting for proper escape interpretation
      ya.emit("shell", { "printf $'\\033]52;c;%s\\007' $(echo -n " .. ya.quote(path) .. " | base64)" })
    else
      -- Local: Use pbcopy (reliable and fast)
      ya.emit("shell", { "printf %s " .. ya.quote(path) .. " | pbcopy" })
    end

    ya.notify({
      title = "Path copied",
      content = path,
      timeout = 2.5,
      level = "info"
    })
  end,
}
