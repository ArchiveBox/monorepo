# TODO: Django Admin Custom Components

Goal: incrementally replace hard-to-style Django admin changelist pieces with small reusable ArchiveBox components, while keeping Django's native admin forms, actions, validation, and selection state as the source of truth.

## Current Target

Start with the changelist selection/count UI shared by:

- `SnapshotAdmin` changelist
- `CrawlAdmin` changelist

This component should centralize:

- total match count and reset-filters/search link
- selected row count
- multi-page "select all matching rows" state
- delegation to Django's native select-across behavior

The first component should replace the current scattered handling around:

- `archivebox/templates/admin/actions.html`
- `archivebox/templates/admin/search_form.html`
- `archivebox/templates/admin/base.html::setupActionSummary()`
- model-specific CSS in `archivebox/templates/static/admin.css`

## Constraints

- Reuse native Django admin code paths for actual behavior.
- Keep Django-rendered form fields and hidden state in the DOM.
- Hide native elements only when we replace the visual presentation.
- Do not reimplement selection logic, bulk-action form submission, or validation in custom JS.
- Prefer a few flat primitives over a hierarchy of helpers/classes.
- Keep component JS scoped and embedded next to the component until there is a clear reason to split it.
- Avoid `!important` fights by rendering our own isolated component markup where needed.

## Django 6 Template Direction

Django 6 supports reusable template partials:

- `{% partialdef name %}` defines a fragment.
- `{% partial name %}` renders it in the current context.
- `template.html#partial_name` can load/include a specific partial.

Use one flat template for changelist pieces:

```text
archivebox/templates/admin/changelist_components.html
```

Start with:

```django
{% partialdef selection_status %}
  ...
{% endpartialdef %}
```

Later add:

- `search_box`
- `action_buttons`
- `filters_toggle`
- `object_tools`
- table/list display pieces

## Native Django State To Preserve

Django admin actions already manage the important state in:

- `span.action-counter`
- `span.all`
- `span.question a`
- `span.clear a`
- `input.select-across`
- `#action-toggle`
- row checkboxes: `#changelist-form input.action-select`

Django's own `actions.js` updates these when the page checkbox, row checkboxes, and select-across link are used. Our component should read these nodes and trigger clicks on them rather than mutating selection state directly.

## Component Shape

Render native state hidden, and render ArchiveBox UI beside it:

```django
<span
  class="abx-changelist-selection"
  data-selection-status
  data-page-count="{{ cl.result_list|length }}"
  data-result-count="{{ cl.result_count }}"
  data-full-result-count="{{ cl.full_result_count|default:cl.result_count }}"
>
  <span class="abx-selection-selected" data-selection-selected>
    0 / {{ cl.result_list|length|intcomma }} selected
  </span>
  <a class="abx-selection-total" href="?" data-selection-total>
    {{ cl.result_count|intcomma }} total
  </a>

  <span class="abx-native-selection-state" hidden>
    <span class="action-counter" data-actions-icnt="{{ cl.result_list|length }}">
      {{ selection_note }}
    </span>
    {% if cl.result_count != cl.result_list|length %}
      <span class="all hidden">{{ selection_note_all }}</span>
      <span class="question hidden">
        <a role="button" href="#">Select all {{ cl.result_count|intcomma }} {{ module_name }}</a>
      </span>
      <span class="clear hidden"><a role="button" href="#">Clear selection</a></span>
    {% endif %}
  </span>
</span>
```

Important: keep the Django classes/names that `actions.js` expects. The native state can be visually hidden, but it must stay in the same `div.actions` scope.

## Vanilla JS Binding Pattern

Use a tiny DOM adapter plus render function:

- `MutationObserver` watches Django's `.action-counter`.
- `change` event on `#changelist-form` catches checkbox changes.
- Clicks on the visible total link delegate to Django's native `.question a` or `#action-toggle`.
- UI writes only update the ArchiveBox component text/classes.

No framework, no custom store, no duplicate state.

```js
function bindSelectionStatus(root) {
  const native = {
    counter: root.querySelector(".action-counter"),
    questionLink: root.querySelector(".question a"),
    clearLink: root.querySelector(".clear a"),
    selectAcross: root.querySelector("input.select-across")
      || document.querySelector("input.select-across"),
    allToggle: document.getElementById("action-toggle"),
  }

  const ui = {
    selected: root.querySelector("[data-selection-selected]"),
    total: root.querySelector("[data-selection-total]"),
  }

  const formatter = new Intl.NumberFormat()

  function parseCounter() {
    const match = native.counter.textContent.match(/(\d+)\s+of\s+(\d+)\s+selected/)
    return {
      selected: match ? Number(match[1]) : 0,
      pageCount: match ? Number(match[2]) : Number(native.counter.dataset.actionsIcnt || 0),
    }
  }

  function render() {
    const {selected, pageCount} = parseCounter()
    const resultCount = Number(root.dataset.resultCount || pageCount)
    const fullCount = Number(root.dataset.fullResultCount || resultCount)
    const selectAcross = native.selectAcross?.value === "1"
    const selectedCount = selectAcross ? resultCount : selected
    const selectedLimit = selectAcross ? resultCount : pageCount

    ui.selected.textContent = `${formatter.format(selectedCount)} / ${formatter.format(selectedLimit)} selected`

    ui.total.textContent = fullCount && fullCount !== resultCount
      ? `${formatter.format(resultCount)} / ${formatter.format(fullCount)} total`
      : `${formatter.format(resultCount)} total`

    root.classList.toggle("has-selection", selected > 0 || selectAcross)
    root.classList.toggle("select-across", selectAcross)
  }

  root.addEventListener("click", (event) => {
    if (!event.target.closest("[data-selection-total]")) return
    event.preventDefault()

    if (root.classList.contains("has-selection") && native.questionLink) {
      native.questionLink.click()
    } else if (native.allToggle && !native.allToggle.checked) {
      native.allToggle.click()
    }

    queueMicrotask(render)
  })

  new MutationObserver(render).observe(native.counter, {
    childList: true,
    characterData: true,
    subtree: true,
  })

  document.querySelector("#changelist-form")?.addEventListener("change", render)
  render()
}

document.querySelectorAll("[data-selection-status]").forEach(bindSelectionStatus)
```

## Reads And Writes

Reads:

- selected/page count from `.action-counter`
- select-across state from `input.select-across`
- result/full count from component `data-*` attributes
- fallback selected count from checked row boxes if needed

Writes:

- visible selected text
- visible total text
- component state classes

Behavior writes:

- trigger `#action-toggle.click()`
- trigger `.question a.click()`
- trigger `.clear a.click()` if we keep an explicit clear affordance

Do not set `select_across`, row checkboxes, or action counter text manually except by using native Django controls.

## First Implementation Steps

1. Create `admin/changelist_components.html` with `selection_status`.
2. Update `admin/actions.html` to include `selection_status` instead of inline custom summary markup.
3. Keep native Django action state nodes in `actions.html`, hidden inside the component.
4. Move `setupActionSummary()` out of global `base.html` into the component's inline script.
5. Remove snapshot/crawl duplicate `.action-summary` CSS and replace it with generic `.abx-changelist-selection` CSS.
6. For snapshots, continue using `SnapshotChangeList.full_result_count`.
7. For crawls, show full count only when Django already has it cheaply; do not add expensive full counts just for UI.
8. Verify:
   - page checkbox updates visible count
   - row checkbox updates visible count
   - clicking total selects all matching rows through Django native `question a`
   - `select_across` hidden input changes to `1`
   - reset link clears filters/search where full result count is available

## Later Components

After selection/count is clean:

1. Search field
   - render search input as a component
   - keep native GET params and form submission
   - support snapshot search mode select via native form fields

2. Action buttons
   - hide native action dropdown/submit
   - render visual buttons
   - on click, set native `select[name=action]`, then click native submit
   - keep action form validation and fields

3. Object tools
   - hide native `.object-tools`
   - render add/link buttons in the toolbar using native `{% change_list_object_tools %}` data or the rendered link as source

4. Filters
   - keep Django filter specs and links
   - render compact toggle/panel component

5. Tables/results
   - migrate only after the toolbar/actions are stable
   - preserve sorting URLs, checkboxes, and list-editable behavior

## Design Rule

If a Django admin widget is easy to style natively, style it.

If styling requires fighting Django CSS/DOM with many overrides, hide the native visual surface and render a small ArchiveBox component that reads from and writes to the native Django state.
