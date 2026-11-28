"""Read-only chronological replay, sharing the live side-selection rules."""
from utils.coinflip_history import History
from utils.coinflip_probe import ProbePlan
from utils.gambling_control import stake_for_losses
import bisect
import random


def generator_base(capital):
    # Reproduce the public generator's detectTier + 100 * 2^tier.
    thresholds = [10,100,1000,5000,10000,20000,40000,75000,100000,200000,500000,1000000,5000000]
    return 100 * 2**bisect.bisect_right(thresholds, capital)


def validate(data):
    if not isinstance(data, dict) or set(data) != {"accountId", "capital", "base", "warmupPercent", "goal", "lossLimit"}:
        raise ValueError("Thông số mô phỏng không hợp lệ.")
    if not isinstance(data["accountId"], str):
        raise ValueError("Chọn tài khoản để đọc lịch sử.")
    for key, low, high in (("capital", 1, 10**12), ("base", 1, 250000), ("warmupPercent", 0, 80)):
        if type(data[key]) is not int or not low <= data[key] <= high:
            raise ValueError(f"{key} phải là số nguyên từ {low} đến {high}.")
    for key in ("goal", "lossLimit"):
        if data[key] is not None and (type(data[key]) is not int or not 1 <= data[key] <= 10**12):
            raise ValueError("Giới hạn mô phỏng phải là số nguyên dương hoặc để trống.")
    return data


def compare(rows, data):
    data = validate(data)
    rows = list(rows)
    if len(rows) < 2:
        raise ValueError("Cần ít nhất 2 ván đã ghi nhận để mô phỏng.")
    warmup = len(rows) * data["warmupPercent"] // 100
    training, testing = rows[:warmup], rows[warmup:]
    results = []
    for mode in ("heads", "tails", "auto100", "auto500", "probe", "probeLossHeads", "probeLossTails", "switchHeads", "switchTails", "generatorHeads", "generatorTails"):
        strategies = ("double",) if mode.startswith("generator") else ("fixed", "double", "bonus")
        for strategy in strategies:
            doubling = strategy != "fixed"
            bonus = strategy == "bonus"
            history = History(training)
            capital, base = data["capital"], data["base"]
            if mode.startswith("generator"):
                base = generator_base(capital)
            probe_mode = mode in ("probe", "probeLossHeads", "probeLossTails")
            plan = ProbePlan("until_loss", "heads" if mode == "probeLossHeads" else "tails") if mode.startswith("probeLoss") else ProbePlan()
            if mode.startswith("switch"):
                plan = ProbePlan("win_switch", "heads" if mode == "switchHeads" else "tails")
            rng = random.Random(42)  # Reproducible simulation; never tune this from future results.
            progression = probes = 0
            balance = peak = capital
            losses = best_losses = wins = played = total_losses = max_stake = drawdown = 0
            stop, stop_at = "complete", None
            curve = [dict(round=0, profit=0)]
            window = 100 if mode == "auto100" else 500
            for index, (message, actual_side, actual_outcome) in enumerate(testing, 1):
                main_stake = stake_for_losses(base, progression, doubling, bonus)
                probe = probe_mode and plan.phase == "probe"
                stake = 1 if probe else main_stake
                profit = balance - capital
                if data["goal"] is not None and profit >= data["goal"]:
                    stop = "goal"
                elif data["lossLimit"] is not None and (profit <= -data["lossLimit"] or profit - main_stake < -data["lossLimit"]):
                    stop = "loss_limit"
                elif main_stake > 250000:
                    stop = "bet_cap"
                elif main_stake > balance:
                    stop = "capital"
                if stop != "complete":
                    stop_at = index
                    break
                # Pick using ONLY prior rows; the current result is still unseen.
                side = history._selection(window)["side"] if mode.startswith("auto") else plan.side if probe_mode or mode.startswith("switch") else "heads" if mode == "generatorHeads" else "tails" if mode == "generatorTails" else mode
                landed = actual_side if actual_outcome == "win" else ("tails" if actual_side == "heads" else "heads")
                won = side == landed
                balance += stake if won else -stake
                max_stake = max(max_stake, stake)
                played += 1
                if won:
                    wins += 1
                    losses = 0
                else:
                    total_losses += 1
                    losses += 1
                    best_losses = max(best_losses, losses)
                if not probe:
                    progression = 0 if won else progression + 1
                else:
                    probes += 1
                if probe_mode or mode.startswith("switch"):
                    plan.complete(won, choose=lambda: rng.choice(("heads", "tails")))
                peak = max(peak, balance)
                drawdown = max(drawdown, peak - balance)
                history.record(message, side, "win" if won else "loss")
                curve.append(dict(round=index, profit=balance-capital))
            results.append(dict(id=f"{mode}-{strategy}", mode=mode,
                                doubling=doubling, bonus=bonus, profit=balance-capital, balance=balance,
                                base=base, probes=probes, applicable=base<=250000,
                                wins=wins, losses=total_losses, played=played, maxDrawdown=drawdown,
                                maxStake=max_stake, maxLossStreak=best_losses,
                                stop=stop, stopAt=stop_at, curve=curve))
    results.sort(key=lambda r: (r["played"]==0, -r["profit"], r["maxDrawdown"], r["id"]))
    return dict(samples=len(rows), warmup=warmup, tested=len(testing), inputs=data, results=results)
