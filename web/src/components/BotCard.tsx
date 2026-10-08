import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { money, percent, percentPlain, ratio, tone } from "../format";
import type { BotSummary } from "../types";
import { Sparkline } from "./Sparkline";

interface Props {
  bot: BotSummary;
  runId: number;
  color: string;
  started: boolean;
}

export function BotCard({ bot, runId, color, started }: Props) {
  const eliminated = bot.status === "eliminated";
  return (
    <li className={`card bot-card${eliminated ? " eliminated" : ""}`} style={{ "--bot": color } as CSSProperties}>
      <Link to={`/bots/${runId}/${bot.id}`} className="card-link" aria-label={`${bot.name}: details`}>
        <div className="bot-head">
          <span className="rank" aria-label={`Rank ${bot.rank}`}>#{bot.rank}</span>
          <span className="emoji" aria-hidden="true">{eliminated ? "💀" : bot.emoji}</span>
          <div className="bot-name">
            <h3>{bot.name}</h3>
            <div className="tags">
              {bot.is_benchmark && <span className="tag tag-bench">Benchmark</span>}
              {eliminated && <span className="tag tag-dead">Eliminated</span>}
            </div>
          </div>
        </div>

        <div className="bot-money">
          <span className="equity num">{money(bot.equity ?? bot.starting_cash)}</span>
          <span className={`ret num ${tone(bot.total_return)}`}>{started ? percent(bot.total_return) : "not started"}</span>
        </div>

        <Sparkline values={bot.sparkline} color={color} baseline={bot.starting_cash} dashed={bot.is_benchmark} />

        <dl className="bot-stats">
          <div>
            <dt>Max drawdown</dt>
            <dd className="num">{percent(bot.max_drawdown)}</dd>
          </div>
          <div>
            <dt>Sharpe</dt>
            <dd className="num">{ratio(bot.sharpe)}</dd>
          </div>
          <div>
            <dt>Trades</dt>
            <dd className="num">{bot.trades}</dd>
          </div>
          <div>
            <dt>Invested</dt>
            <dd className="num">{percentPlain(bot.exposure)}</dd>
          </div>
        </dl>
      </Link>
    </li>
  );
}
