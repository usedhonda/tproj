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
      -- ファイル → yazi.toml の [open] 設定に従って開く
      ya.emit("open", { hovered = true })
    end
  end,
}
