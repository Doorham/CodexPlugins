# Release repository instructions

- This branch distributes the formal CodexTools installer and user documentation. Legacy scattered source is preserved on legacy/scattered-toolbox; do not restore its bootstrap instructions here.
- Publish tested Setup assets through GitHub Releases. Keep the existing CodexTools-Plugins catalog address stable.
- Do not include credentials, personal state, company connection settings, private development paths or diagnostic logs.
- Plugin business code and runtime dependencies belong to independently versioned plugins. Verify plugin updates with an unchanged host executable.
