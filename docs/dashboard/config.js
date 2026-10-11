// Runtime settings. The deploy workflow (.github/workflows/pages.yml) replaces the
// placeholder with the CARTO_KEY repository secret; CARTO basemaps need a key.
window.DASHBOARD_CONFIG = { cartoKey: '__CARTO_KEY__' };
