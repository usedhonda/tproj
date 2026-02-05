--- @sync entry
return {
  entry = function()
    local h = cx.active.current.hovered
    local dir

    if h and h.cha.is_dir then
      dir = tostring(h.url)
    else
      dir = tostring(cx.active.current.cwd)
    end

    local script = os.getenv("HOME") .. "/.config/yazi/plugins/open-terminal.yazi/toggle.sh"
    ya.emit("shell", { "bash " .. ya.quote(script) .. " " .. ya.quote(dir) })
  end,
}
