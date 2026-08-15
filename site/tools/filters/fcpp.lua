-- fcpp.lua — pandoc filter turning the book's LaTeX constructs into web-friendly HTML.
--
-- Runs on one chapter at a time. `chapnum` metadata drives figure/table/theorem
-- numbering; collected labels are dumped as JSON to `refsfile` so the Python
-- driver can resolve cross-page references after the chapter is split into pages.

local chapnum = '1'
local refsfile = nil

local labels = {}     -- id -> {kind = ..., text = ...}
local counters = {}
local figcount = 0
local tabcount = 0

local BOX = {
  fcpptheorem     = {name = '定理', cls = 'theorem',     numbered = true},
  fcpplemma       = {name = '引理', cls = 'lemma',       numbered = true},
  fcppproposition = {name = '命题', cls = 'proposition', numbered = true},
  fcppcorollary   = {name = '推论', cls = 'corollary',   numbered = true},
  fcppdefinition  = {name = '定义', cls = 'definition',  numbered = true},
  fcppexample     = {name = '例',   cls = 'example',     numbered = true},
  fcppremark      = {name = '注',   cls = 'remark',      numbered = false},
  fcppproof       = {name = '证明', cls = 'proof',       numbered = false},
}

local function esc(s)
  return (s:gsub('&', '&amp;'):gsub('<', '&lt;'):gsub('>', '&gt;'):gsub('"', '&quot;'))
end

-- `text` is what \cref prints ("图 3.1"); `name` is what \nameref prints.
local function record(id, kind, text, name)
  if id and id ~= '' then
    labels[id] = {kind = kind, text = text, name = name or text}
  end
end

-- Prepend `text` to a node's caption, in place.
local function prefix_caption(node, text)
  local cap = node.caption
  if cap == nil or cap.long == nil then return end
  local blocks = cap.long
  if #blocks > 0 and (blocks[1].t == 'Plain' or blocks[1].t == 'Para') then
    blocks[1].content:insert(1, pandoc.Space())
    blocks[1].content:insert(1, pandoc.Str(text))
  else
    blocks:insert(pandoc.Plain(pandoc.Inlines({pandoc.Str(text)})))
  end
  node.caption = cap
end

local function has_caption(node)
  return node.caption ~= nil and node.caption.long ~= nil and #node.caption.long > 0
end

local SUBLETTERS = {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'}

-- Figures and tables are numbered top-down so nested subfigures come out in
-- reading order.
local pending_table_id = nil

local numbering = {
  traverse = 'topdown',

  -- pandoc hangs a table float's \label on a wrapping Div rather than on the
  -- Table itself; remember it for the Table handler below.
  Div = function(d)
    if d.identifier ~= '' then
      for _, b in ipairs(d.content) do
        if b.t == 'Table' then pending_table_id = d.identifier end
      end
    end
    return nil
  end,

  Figure = function(fig)
    local subs = {}
    for _, b in ipairs(fig.content) do
      if b.t == 'Figure' then table.insert(subs, b) end
    end

    figcount = figcount + 1
    local num = '图 ' .. chapnum .. '.' .. figcount

    if #subs > 0 then
      -- pandoc copies the last subfigure's label and caption onto the wrapper;
      -- drop both so the anchor stays unique and the caption is not repeated.
      local outer_cap = has_caption(fig) and pandoc.utils.stringify(fig.caption.long) or nil
      local echoed = false
      for _, s in ipairs(subs) do
        if s.identifier == fig.identifier then fig.identifier = '' end
        if outer_cap and outer_cap == pandoc.utils.stringify(s.caption.long) then
          echoed = true
        end
      end
      if echoed then
        local cap = fig.caption
        cap.long = pandoc.Blocks({})
        fig.caption = cap
      end
      for i, s in ipairs(subs) do
        local tag = num .. '(' .. (SUBLETTERS[i] or i) .. ')'
        prefix_caption(s, tag)
        record(s.identifier, 'fig', tag)
      end
      if has_caption(fig) then prefix_caption(fig, num) end
    else
      prefix_caption(fig, num)
    end
    record(fig.identifier, 'fig', num)
    return fig, false   -- children already handled
  end,

  Table = function(tbl)
    tabcount = tabcount + 1
    local num = '表 ' .. chapnum .. '.' .. tabcount
    prefix_caption(tbl, num)
    record(tbl.identifier ~= '' and tbl.identifier or pending_table_id, 'tab', num)
    pending_table_id = nil
    return tbl, false
  end,
}

local elements = {
  -- Theorem-like tcolorbox environments, rewritten by preprocess.py into
  -- \begin{fcpp<kind>} … with the title carried by a \subparagraph.
  Div = function(el)
    local key
    for _, c in ipairs(el.classes) do
      if BOX[c] then key = c end
    end
    if not key then return nil end
    local info = BOX[key]

    local id, title = '', ''
    local body = {}
    for i, b in ipairs(el.content) do
      if i == 1 and b.t == 'Header' then
        -- unlabelled boxes get an id pandoc derived from the title; ignore it
        id = b.identifier:match('^%a[%w]*:') and b.identifier or ''
        title = pandoc.utils.stringify(b.content)
      else
        table.insert(body, b)
      end
    end

    local head = info.name
    if info.numbered then
      counters[key] = (counters[key] or 0) + 1
      head = head .. ' ' .. chapnum .. '.' .. counters[key]
    end
    record(id, info.cls, head, title ~= '' and title or head)

    local open = '<div class="fcpp-box fcpp-' .. info.cls .. '"'
    if id ~= '' then open = open .. ' id="' .. esc(id) .. '"' end
    open = open .. '>\n<p class="fcpp-box-title"><span class="fcpp-box-label">'
      .. esc(head) .. '</span>'
    if title ~= '' then open = open .. esc(title) end
    open = open .. '</p>'

    local out = pandoc.Blocks({pandoc.RawBlock('html', open)})
    out:extend(body)
    out:insert(pandoc.RawBlock('html', '</div>'))
    return out
  end,

  -- gfm drops heading ids, so emit an explicit anchor for every LaTeX \label.
  Header = function(h)
    local id = h.identifier
    if id == '' or not id:match('^%a[%w]*:') then return nil end
    record(id, 'sec', pandoc.utils.stringify(h.content))
    return {
      pandoc.RawBlock('html', '<a class="fcpp-anchor" id="' .. esc(id) .. '"></a>'),
      h,
    }
  end,

  -- mdBook ships MathJax 2 with its stock config, which only recognises
  -- \(…\) and \[…\] — not the $…$ the gfm writer would emit. Markdown would
  -- eat the backslashes (and read `a_{n-1}` as emphasis), so every character
  -- that means something to CommonMark goes out as a numeric entity; the
  -- browser turns it back into text before MathJax typesets it.
  Math = function(m)
    local open, close = '\\(', '\\)'
    if m.mathtype == 'DisplayMath' then open, close = '\\[', '\\]' end
    local tex = (open .. m.text .. close):gsub('[\\`*_%[%]<>&{}#|~]', function(c)
      return '&#' .. string.byte(c) .. ';'
    end)
    return pandoc.RawInline('html', tex)
  end,

  -- \cref/\nameref/\ref were rewritten to \ref{<kind>--<label>}; leave a token
  -- for the driver, which alone knows which page each label ended up on.
  Link = function(el)
    local ref = el.attributes['reference']
    if not ref then return nil end
    local kind, label = ref:match('^(%a+)%-%-(.+)$')
    if not kind then return nil end
    return pandoc.RawInline('html', '@@XREF|' .. kind .. '|' .. label .. '@@')
  end,
}

local function json_escape(s)
  s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\t', '\\t')
  return s
end

local dump = {
  Pandoc = function(doc)
    if not refsfile then return doc end
    local parts = {}
    for id, v in pairs(labels) do
      table.insert(parts, string.format('"%s":{"kind":"%s","text":"%s","name":"%s"}',
        json_escape(id), json_escape(v.kind), json_escape(v.text), json_escape(v.name)))
    end
    table.sort(parts)
    local fh = io.open(refsfile, 'w')
    fh:write('{' .. table.concat(parts, ',') .. '}')
    fh:close()
    return doc
  end,
}

return {
  {
    Meta = function(m)
      if m.chapnum then chapnum = pandoc.utils.stringify(m.chapnum) end
      if m.refsfile then refsfile = pandoc.utils.stringify(m.refsfile) end
      return m
    end,
  },
  numbering,
  elements,
  dump,
}
