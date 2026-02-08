--- @sync entry
return {
  entry = function()
    local h = cx.active.current.hovered

    if not h then
      ya.notify({ title = "Error", content = "No file selected" })
      return
    end

    local path = tostring(h.url)

    ya.emit("shell", { "printf '\\033]52;c;%s\\a' $(echo -n " .. ya.quote(path) .. " | base64)" })

    ya.notify({
      title = "Path copied",
      content = path,
      timeout = 2.5,
      level = "info"
    })
  end,
}
