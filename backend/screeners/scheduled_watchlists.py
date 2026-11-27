"""Rank the scheduled alert candidates from the same checks used for the CSV."""

from math import isfinite

from screeners.output_formatter import to_tv


def _breakout_tier(check, config):
    if not check['avwap'] < check['close'] <= check['avwap'] * (1 + config['ceiling']):
        return None
    attempts = check['failed_attempts']
    if check['status'] in {'passed', 'failed_attempts', 'turnover', 'outside_ceiling'}:
        if attempts <= 2:
            return attempts
        if attempts <= config['max_failed_attempts']:
            return 3
    if check['status'] == 'no_sustained_breakout' and check.get('pending_above') and attempts == 0:
        return 4
    return None


def _pullback_tier(check, config):
    if check['status'] not in {'passed', 'crosses', 'outside_proximity', 'turnover'}:
        return None
    dist = check['distance_pct']
    low, high = config['proximity_low_pct'], config['proximity_high_pct']
    crosses = check['crosses']
    limit = config['max_brief_crosses']
    if not low <= dist <= high + 1:
        return None
    if crosses <= limit:
        return 0 if dist <= high else 1
    if crosses == limit + 1:
        return 2
    return None


def scheduled_watchlists(logic, screener, config):
    if logic == 'breakout':
        tier_for = _breakout_tier
        labels = ['Pure breakout', 'Retry 1 · one prior failure', 'Retry 2 · two prior failures',
                  'Other configured retries', 'Pending · first break still confirming']
    else:
        tier_for = _pullback_tier
        low, high = config['proximity_low_pct'], config['proximity_high_pct']
        limit = config['max_brief_crosses']
        labels = [f'Strict pullback · {low:g}% to {high:g}%',
                  f'Near AVWAP · above {high:g}% through {high + 1:g}%',
                  f'One extra cross · {limit + 1} spells below AVWAP']

    groups = [[] for _ in labels]
    for symbol, diagnostic in sorted(screener.diagnostics.items()):
        ranks = []
        for check in diagnostic.get('periods', {}).values():
            turnover, distance = check.get('turnover'), check.get('distance_pct')
            if (turnover is None or distance is None or not isfinite(turnover)
                    or not isfinite(distance) or turnover < config['min_turnover']):
                continue
            rank = tier_for(check, config)
            if rank is not None:
                ranks.append(rank)
        if ranks:
            ticker = symbol.removesuffix(screener.market_suffix) if screener.market_suffix else symbol
            groups[min(ranks)].append(to_tv(ticker, screener.market_suffix, screener.market))

    return [
        {'label': label, 'symbols': symbols}
        for index, (label, symbols) in enumerate(zip(labels, groups))
        if logic != 'breakout' or index != 3 or symbols
    ]
