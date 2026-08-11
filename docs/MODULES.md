# ChurchBoard 2 modules

ChurchBoard 2 is a private beta of a module-based production platform. Open **Modules** from the ChurchBoard control page to add, remove, configure, and update integrations. Adding a module also adds every required module; for example, **ProPresenter → Services LIVE** installs both the Planning Center and ProPresenter modules before enabling their interaction.

Each module manifest keeps these concerns together:

- identity, vendor, version, category, and update policy;
- required modules and manual prerequisites;
- capabilities it provides and consumes;
- its Producer or dashboard pages;
- its page widgets and their default size/settings;
- its setup guide, configuration link, styles, and browser renderer.

This makes a page the output of installed modules instead of a hard-coded list in the ChurchBoard shell. The page editor builds its widget palette from installed module manifests. Saving or importing a page automatically installs the owner of each widget. A module can register its own renderer and assets through `ChurchBoardModules.registerWidget(...)`; an unknown module widget is valid data and no longer requires changing the base `Widget` model.

## Current modules

The private beta includes modules for ChurchBoard pages, Planning Center Services, ProPresenter, ProPresenter-to-Services-LIVE interaction, Shure Wireless, Sennheiser Wireless, Open Sound Meter, OBS Studio, Restream, multi-provider livestream monitoring, NDI video, Producer, and Producer Intercom.

The **Interactions** category is intentional. An interaction that combines two sources belongs in a small bridge module which consumes published contracts, rather than either source reaching into the other's implementation. For example:

- Planning Center provides `churchboard.service-plan/v1`, `churchboard.people/v1`, `churchboard.media/v1`, and `churchboard.timing/v1`.
- ProPresenter provides `churchboard.presentation/v1` and `churchboard.presentation-control/v1`.
- The Services LIVE bridge consumes the service-plan and presentation contracts and provides `churchboard.services-live-sync/v1`.

Optional dependencies end in `?`. Wireless modules, for example, can provide microphone telemetry without Planning Center, while a scheduled-position page can combine microphone data and people when both contracts are available.

## Setup and updates

Select a module's **Details** button for a short setup guide and its dependency list. Manual prerequisites are shown inline. The NDI module links directly to NDI's official SDK download, explains the standard install location, and then links to ChurchBoard's NDI configuration.

ChurchBoard 2 initially ships the reviewed module catalog with the application. The module manager tracks each installed module's version independently and applies newer bundled module versions when **Automatically apply bundled module updates** is enabled. This preserves a safe local beta while establishing the same per-module lifecycle needed for a signed remote module catalog later.

## Adding a module during the beta

1. Add its manifest to `app/modules/builtin.py`. Give it a stable lowercase ID, independent version, dependencies, provided/consumed contracts, and any widgets/pages.
2. Put module-owned browser assets under `app/static/modules/<module-id>/` and declare them under `frontend.styles` or `frontend.scripts`.
3. From the module script, register each visual page widget with `ChurchBoardModules.registerWidget(widgetType, renderer)`.
4. Keep cross-source behavior in an interaction module. Depend on stable contracts instead of importing another module's private state.
5. Add registry, API, page-import, and browser tests. A missing module must degrade to a clear placeholder rather than break the page.

The current integrations use the `legacy-adapter` renderer while they are migrated one at a time. The host and schema are already dynamic, so new module-owned widget renderers do not require another type branch in the base shell.
