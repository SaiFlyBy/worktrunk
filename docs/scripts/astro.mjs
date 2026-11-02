// Astro's CLI initializes telemetry before loading project configuration.
// Set the opt-out before importing the CLI, without changing global settings.
process.env.ASTRO_TELEMETRY_DISABLED = '1';

await import('../node_modules/astro/bin/astro.mjs');
