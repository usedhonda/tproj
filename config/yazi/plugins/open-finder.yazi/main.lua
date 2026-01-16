--- @sync entry
return {
  entry = function()
    local h = cx.active.current.hovered

    if not h then
      ya.emit("open", { hovered = true })
      return
    end

    if h.cha.is_dir then
      -- ディレクトリ → Finder で開く
      local path = tostring(h.url)
      ya.emit("shell", { "open " .. ya.quote(path) })
    else
      -- ファイル → 通常通りオープン
      ya.emit("open", { hovered = true })
    end
  end,
}
