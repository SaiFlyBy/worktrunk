// Astro 7.4.4 expects this small interface. Keep collection unavailable even
// when Astro is started directly, before project configuration is loaded.
export class AstroTelemetry {
  async notify() {}
  async record() {}
  setEnabled(enabled) {
    if (enabled) throw new Error('Astro telemetry is disabled in this fork');
  }
  clear() {}
}
