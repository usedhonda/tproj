--- @sync entry
return {
  entry = function()
    local h = cx.active.current.hovered

    if not h then
      ya.notify({ title = "Error", content = "No file selected" })
      return
    end

    local path = tostring(h.url)

    ya.emit("shell", { "echo " .. ya.quote(path) .. " | pbcopy" })

    ya.notify({
      title = "Path copied",
      content = path,
      timeout = 2.5,
      level = "info"
    })
  end,
}
