# Reusable prompt() replacement modal for Electron renderers

Drop these three snippets into any Electron app. Together they form a `showInput(title, hint, defaultValue) → Promise<string|null>` that fully replaces `window.prompt()` and integrates with the rest of the UI.

## HTML (paste into your renderer's `index.html`, near other modals)

```html
<!-- Generic single-line input modal (replaces window.prompt) -->
<div id="input-modal" class="modal hidden">
  <div class="modal-body" style="max-width:480px">
    <h3 id="input-title">Input</h3>
    <div id="input-hint" class="modal-hint"></div>
    <input id="input-text" style="width:100%;padding:8px 10px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#e6edf3;font-size:14px;margin-top:8px" />
    <div style="margin-top:14px;text-align:right;display:flex;gap:8px;justify-content:flex-end">
      <button id="input-cancel" class="btn ghost">Cancel</button>
      <button id="input-ok" class="btn primary">OK</button>
    </div>
  </div>
</div>
```

## CSS

```css
.modal { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center; }
.modal.hidden { display: none; }
.modal-body { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
  padding: 24px; min-width: 360px; box-shadow: 0 8px 32px rgba(0,0,0,0.5); }
.modal-body h3 { margin: 0 0 12px; color: #e6edf3; }
.modal-hint { color: #8b949e; font-size: 12px; }
```

## JS (drop into any module that needs `prompt` replacement)

```js
function showInput(title, hint, defaultValue) {
  return new Promise((resolve) => {
    const $ = (id) => document.getElementById(id);
    $("input-title").textContent = title;
    $("input-hint").textContent = hint || "";
    const inp = $("input-text");
    inp.value = defaultValue || "";
    $("input-modal").classList.remove("hidden");
    setTimeout(() => { inp.focus(); inp.select(); }, 50);

    const ok = $("input-ok"), cancel = $("input-cancel");
    const close = () => {
      $("input-modal").classList.add("hidden");
      ok.removeEventListener("click", onOk);
      cancel.removeEventListener("click", onCancel);
      inp.removeEventListener("keydown", onKey);
    };
    const onOk = () => { const v = inp.value; close(); resolve(v); };
    const onCancel = () => { close(); resolve(null); };
    const onKey = (e) => {
      if (e.key === "Enter") { e.preventDefault(); onOk(); }
      else if (e.key === "Escape") onCancel();
    };
    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", onCancel);
    inp.addEventListener("keydown", onKey);
  });
}
```

## Variant: confirm() replacement

```js
function showConfirm(title, msg, dangerous = false) {
  return new Promise((resolve) => {
    // Similar structure, but OK button has danger styling when dangerous=true
    // Resolves true on OK, false on Cancel/Escape/close
    // ... use same modal skeleton without the input
  });
}
```

## Variant: chip-picker (tag selector with presets + custom input)

This is what gets used when the user clicks `+` on a tag column in AdsPower-style UIs.

```js
function showTagPicker(title, presets) {
  // presets: [{name, color}]
  // Returns Promise<string|null> — selected/typed tag name
  return new Promise((resolve) => {
    const list = document.getElementById("tag-pick-list");
    list.innerHTML = presets.map((t) =>
      `<button class="tag-pick-chip" data-name="${escapeHtml(t.name)}"
        style="background:${t.color};border-color:${t.color}">
        ${escapeHtml(t.name)}
      </button>`
    ).join("");
    // + custom-input + add/close handlers, similar to showInput
  });
}
```

## Why a Promise wrapper

- Call-site code reads almost identical to `const v = prompt(...)`:
  `const v = await showInput("Tag", "", ""); if (!v) return;`
- Composes cleanly with `await window.api.xxx(...)` patterns
- Easy to upgrade: change return value to `{value, action: 'ok'|'cancel'}` if you need richer signals

## Pitfalls when implementing

- **Re-binding listeners on every show:** if you forget `removeEventListener` in `close()`, opening the modal a second time double-fires handlers. The template above handles this.
- **Focus race:** without `setTimeout(focus, 50)`, the `<input>` won't actually receive focus in some Electron versions because the modal's `display:none → flex` transition isn't complete yet.
- **Enter inside `<textarea>` should NOT submit:** if you adapt this for multi-line input, drop the `Enter → onOk` handler.
- **Escape key conflicts with parent modals:** if your input modal is opened from inside another modal, the Escape handler may close both. Use `event.stopPropagation()` in the keydown handler.
