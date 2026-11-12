export const markets = ['NSE', 'BSE', 'NASDAQ', 'NYSE'];
export const timeframes = ['daily', 'weekly', 'monthly'] as const;
export const strategies = ['breakout', 'pullback'];

const common = { min_turnover: [0, 1e15, false] } as const;
const ruleRanges = {
  breakout: {
    ...common, tolerance_below_avwap: [0, 1, false], ceiling: [0, 10, false],
    sustain_periods: [1, 100, true], max_failed_attempts: [0, 100, true],
  },
  pullback: {
    ...common, proximity_low_pct: [-100, 1000, false], proximity_high_pct: [-100, 1000, false],
    max_brief_crosses: [0, 100, true], min_periods_old: [0, 520, true],
  },
} as const;

export function settingsError(logic: string, timeframe: string, params: unknown): string | undefined {
  if (logic !== 'breakout' && logic !== 'pullback') return 'Choose a valid strategy.';
  const limits: Record<string, number> = { daily: 2500, weekly: 520, monthly: 240 };
  if (!timeframes.some((value) => value === timeframe)) return 'Choose a valid timeframe.';
  if (!params || typeof params !== 'object' || Array.isArray(params)) return 'Enter valid scan settings.';
  const settings = params as Record<string, unknown>;
  const rules = ruleRanges[logic] as Record<string, readonly [number, number, boolean]>;
  for (const [key, value] of Object.entries(settings)) {
    if (key === 'anchor_periods') {
      const max = limits[timeframe];
      if (!Array.isArray(value) || value.length < 1 || value.length > 12 ||
          value.some((period) => !Number.isInteger(period) || period < 1 || period > max)) {
        return `Enter 1–12 whole-number anchor periods between 1 and ${max}.`;
      }
      continue;
    }
    if (!Object.prototype.hasOwnProperty.call(rules, key)) return `Unknown setting ${key}.`;
    const [min, max, integer] = rules[key];
    if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max ||
        (integer && !Number.isInteger(value))) {
      return `Enter ${key.replace(/_/g, ' ')} between ${min} and ${max}${integer ? ' as a whole number' : ''}.`;
    }
  }
  if (logic === 'pullback' &&
      Number(settings.proximity_low_pct ?? 0) > Number(settings.proximity_high_pct ?? 2)) {
    return 'Proximity low must be at or below proximity high.';
  }
}

export function scheduledDefaults(logic: string, timeframe: string) {
  const base = {
    min_turnover: 10000000,
    anchor_periods: timeframe === 'daily' ? [180, 365, 550, 730, 900] : [52, 104, 156, 208, 260],
  };
  return logic === 'breakout'
    ? { ...base, tolerance_below_avwap: 0.05, ceiling: 0.10, sustain_periods: 3, max_failed_attempts: 0 }
    : { ...base, proximity_low_pct: 0, proximity_high_pct: 2, max_brief_crosses: 3, min_periods_old: 20 };
}
