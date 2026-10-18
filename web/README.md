# Coverage dashboard

React + Vite with locally owned shadcn/ui components (Radix Lyra) and Tailwind v4.
The existing TanStack charts and coverage/comparison models are independent of
the component layer.

## Development

```sh
npm ci
npm run dev
npm run check
npm test
npm run build
```

The checked-in `public/history.json` is intentionally empty. For populated local
review, copy the published dashboard's history there temporarily and restore the
empty file before committing. Save screenshots under `screenshots/` (gitignored),
not `dist/` or a temporary directory: builds replace `dist/`.

Production builds prerender the dashboard into `dist/index.html` from
`public/history.json`, so the page has useful content before the browser finishes
loading the history file and JavaScript. The client still fetches the history to
enable interactions and refresh the rendered dashboard.

## Visual system

- Compact test-lab console, not a general-purpose dashboard template.
- Charcoal or cool white surfaces; blue interactions; amber caveats; red failures.
  Passing results use neutral blue-gray, not a green theme.
- Barlow Condensed for headings, Source Sans 3 for controls and reading, IBM Plex
  Mono for identifiers and measurements. Fonts are self-hosted.
- Semantic theme tokens and domain layouts live in `src/style.css`. Shared
  control styles and their variants live in `src/components/ui/`.
- The small shadcn state-selector aliases are kept in `components/ui/variants.css`;
  the scaffolding CLI is not an application or build dependency.
- Trends is the initial view. Cases, Trends and Evidence share one selected run.
  Failure shortcuts open Cases directly. Inspecting a case opens a
  modal sheet without discarding the search, comparison, filter or scroll position.
- Each run initially shows verified failures, or setup errors when there are no
  failed cases. Healthy or unverified runs show all cases. An explicit filter choice
  is preserved when switching tabs; All cases is always one click away.
- Radix handles tabs, toggle groups, disclosures and sheet keyboard/focus behavior.
  Selects intentionally use the shadcn native-select component.

`components.json` records the registry setup. Preview upstream changes with
`npx shadcn@latest add <component> --diff` before updating: components contain local
variants that must be preserved. See `THIRD_PARTY_NOTICES.md` for their license.
