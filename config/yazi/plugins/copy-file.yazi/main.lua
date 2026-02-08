--- @sync entry
return {
  entry = function()
    local h = cx.active.current.hovered

    if not h then
      ya.notify({ title = "Error", content = "No file selected" })
      return
    end

    if h.cha.is_dir then
      ya.notify({ title = "Error", content = "Cannot copy directory content" })
      return
    end

    local path = tostring(h.url)
    ya.emit("shell", { "printf '\\033]52;c;%s\\a' $(cat " .. ya.quote(path) .. " | base64)" })

    ya.notify({
      title = "File content copied",
      content = h.name,
      timeout = 2.5,
      level = "info"
    })
  end,
}
