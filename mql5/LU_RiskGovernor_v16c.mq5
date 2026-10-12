//+------------------------------------------------------------------+
//|                                        LU_RiskGovernor_v16c.mq5 |
//|  LU-POI trader - v16c-A ACCOUNT RISK LAYER as an MQL5 Expert     |
//|                                                                  |
//|  Final result of the v16c study (study_results/LESS_DD_V16C.md): |
//|  v16c-A = v16b-A + dd_throttle_pct=3.5, dd_throttle_scale=0.5,   |
//|  dd_throttle_tfs=M15|M20|M30|H1.  Full year Sep25-Sep26 ($10k,   |
//|  1 % risk): max DD -5.07 % (was -5.55), net +34 092 $ (+33 831),  |
//|  PF 2.967, ulcer 1.628 (1.691), OOS DD -5.07, 13/13 months.       |
//|                                                                  |
//|  This EA reproduces, 1:1 with trader.py / lubot/portfolio_sim.py:|
//|   * DRAWDOWN THROTTLE  new plans x scale while the account's     |
//|     equity (or balance) is > X % below its running PEAK          |
//|     (step or linear ramp; per-timeframe scope; peak persisted)   |
//|   * DAY SOFT CAP       new plans x scale once the day's equity   |
//|     is X % below the day-start equity (nothing flattened)        |
//|   * OPEN-RISK CAP      sum of risk-at-stop of the open legs      |
//|     (BE legs = 0) + optional pending risk <= X % eq; fit / skip  |
//|   * LOSS-STREAK THROTTLE (control lever)                         |
//|   * DAILY / TOTAL LOSS LIMITS (v10: flatten, cancel, halt)       |
//|  Two modes (input Mode):                                         |
//|   GOVERNOR   - the Python bot (run_trader.bat) keeps finding the |
//|     zones; before placing an order it writes a request line to   |
//|     MQL5\Files\<RequestFile>; this EA answers with the allowed    |
//|     lot multiplier in <ResponseFile>.  It ALSO enforces the hard |
//|     limits on every order/position carrying <GovernMagic>, and   |
//|     (optionally) trims pending orders that violate the cap.      |
//|   STANDALONE - the EA trades its own simple limit-at-zone entry  |
//|     (last swing-based supply/demand box on the chart TF) with    |
//|     the v10 ladder 0.6/1.2/2.4/4.8 R, BE after leg 1, +0.3 R     |
//|     after leg 2, under the SAME risk layer.  No ML quality model |
//|     (that part of the Python bot is not ported) - standalone     |
//|     numbers will differ from the study.                          |
//|                                                                  |
//|  Request/response protocol (GOVERNOR):                           |
//|   request : "<id>;<tf>;<side>;<entry>;<sl>;<risk_scale>;<grid>"  |
//|             tf = M5|M10|M15|M20|M30|H1, side = buy|sell,         |
//|             risk_scale = multiplier already applied by the bot,  |
//|             grid = 1 for a grid deep leg (never throttled)       |
//|   response: "<id>;<multiplier>;<reason>"  multiplier 0 = skip    |
//|  (c) LU-POI project, 2026.  MIT.                                 |
//+------------------------------------------------------------------+
#property copyright "LU-POI project"
#property link      "https://github.com/MHD-Amini/webapp"
#property version   "1.600"
#property strict
#property description "v16c-A drawdown-throttle risk layer (3.5 % / x0.5 / M15|M20|M30|H1) + day soft cap + open-risk cap + loss limits"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--------------------------------------------------------------------
// INPUTS  (defaults = v16c-A as shipped in run_trader.bat)
//--------------------------------------------------------------------
enum ENUM_LU_MODE { MODE_GOVERNOR = 0, MODE_STANDALONE = 1 };
enum ENUM_DD_BASIS { DD_EQUITY = 0, DD_BALANCE = 1 };
enum ENUM_OR_MODE { OR_FIT = 0, OR_SKIP = 1 };

input group "=== Mode ==="
input ENUM_LU_MODE Mode                 = MODE_GOVERNOR;   // GOVERNOR: size the Python bot's plans | STANDALONE: own entries
input long         GovernMagic          = 0;               // GOVERNOR: magic of the Python bot (0 = every order/position)
input long         OwnMagic             = 160300;          // STANDALONE: this EA's magic
input string       RequestFile          = "lu_risk_request.txt";   // GOVERNOR: MQL5\Files\ (written by the bot)
input string       ResponseFile         = "lu_risk_response.txt";  // GOVERNOR: MQL5\Files\ (written by this EA)
input string       StateFile            = "lu_risk_state_v16c.txt";// persisted peak / day / halt state (Common\Files)
input bool         TrimPendingOrders    = false;           // GOVERNOR: delete pending orders that breach the open-risk cap

input group "=== Base risk (BASE string of the study) ==="
input double       RiskPct              = 1.0;             // % of equity risked per plan (entry -> SL), before multipliers
input ENUM_DD_BASIS SizeOn              = DD_EQUITY;       // size_on: equity (compounding) | balance
input int          MaxOpenPositions     = 4;               // max_open_positions (plans)
input int          MaxPendingOrders     = 10;              // max_pending_orders

input group "=== v16c DRAWDOWN THROTTLE (v16c-A: 3.5 / 0.5 / step / equity / M15|M20|M30|H1) ==="
input double       DdThrottlePct        = 3.5;             // dd_throttle_pct: throttle while the account is > this % below its peak (0 = off)
input double       DdThrottleScale      = 0.5;             // dd_throttle_scale: multiplier for NEW plans (0 = no new plans)
input double       DdThrottleRamp       = 0.0;             // dd_throttle_ramp: >0 = linear ramp over this many pt instead of a step
input ENUM_DD_BASIS DdBasis             = DD_EQUITY;       // dd_basis: equity (closed + floating) | balance
input string       DdThrottleTfs        = "M15|M20|M30|H1";// dd_throttle_tfs: timeframes throttled ("" = every timeframe)

input group "=== v16c DAY SOFT CAP (v16c-B adds 1.5 / 0.5; v16c-A = off) ==="
input double       DaySoftLossPct       = 0.0;             // day_soft_loss_pct: equity <= day start x (1 - x %) -> scale new plans (0 = off)
input double       DaySoftScale         = 0.5;             // day_soft_scale (0 = skip new plans for the rest of the day)

input group "=== v16c OPEN-RISK CAP (studied, NOT shipped: 0 = off) ==="
input double       MaxOpenRiskPct       = 0.0;             // max_open_risk_pct: open risk-at-stop + new plan <= this % eq (0 = off)
input ENUM_OR_MODE OpenRiskMode         = OR_FIT;          // open_risk_mode: fit the new plan into the budget | skip it
input bool         OpenRiskPending      = false;           // open_risk_pending: count pending orders' initial risk too

input group "=== v16c LOSS-STREAK THROTTLE (control, NOT shipped: 0 = off) ==="
input int          StreakN              = 0;               // streak_n: consecutive losses (r <= -StreakLossR) that arm the throttle
input double       StreakScale          = 0.5;             // streak_scale
input double       StreakDays           = 5.0;             // streak_days: losses older than this drop out
input double       StreakLossR          = 0.2;             // mart_loss_r: a close counts as a loss when r_net <= -this

input group "=== v10 ACCOUNT PROTECTION (shipped: 4.5 / 9.0) ==="
input double       MaxDailyLossPct      = 4.5;             // max_daily_loss_pct: equity <= day start x (1 - x %) -> flatten, no new orders today
input double       MaxTotalLossPct      = 9.0;             // max_total_loss_pct: equity <= start balance x (1 - x %) -> flatten, HALT

input group "=== STANDALONE entry (no ML model - see README_MQL5.md) ==="
input ENUM_TIMEFRAMES ZoneTf            = PERIOD_M15;      // timeframe of the zone scan (its name is what the throttle scope sees)
input int          SwingBars            = 5;               // fractal half-width for the swing that builds the zone
input double       MaxZoneAtr           = 1.0;             // skip zones taller than this x ATR(14) of ZoneTf
input double       MinZoneUsd           = 0.8;             // skip zones thinner than this ($)
input double       MaxDistanceAtr       = 3.0;             // zone must be within this x ATR of the price
input int          MaxPendingBars       = 300;             // cancel a pending order after this many bars of ZoneTf
input string       TpLevelsR            = "0.6|1.2|2.4|4.8"; // tp_levels (R)
input string       TpFracs              = "1|1|1|1";       // tp_fracs (relative)
input string       SlAfterLeg           = "0|0.3|x|x";     // sl_after_leg: stop (R from entry) after the k-th leg closes, x = leave
input int          Slippage             = 20;              // deviation (points) for market orders

//--------------------------------------------------------------------
// GLOBAL STATE (mirrors trader.py State.risk / PortfolioSimulator)
//--------------------------------------------------------------------
CTrade          g_trade;
CPositionInfo   g_pos;
COrderInfo      g_ord;
CSymbolInfo     g_sym;
CAccountInfo    g_acc;

double   g_start_balance   = 0.0;      // start balance for the total-loss limit
double   g_peak            = 0.0;      // running peak of the dd basis   (= PortfolioSimulator.peak_equity)
string   g_day             = "";       // server day of day_start_equity (YYYY.MM.DD)
double   g_day_start       = 0.0;      // day-start equity (= day_start_balance in the sim: balance + floating at the rollover)
string   g_daily_halt_day  = "";       // day on which the daily limit was hit ("" = trading allowed)
bool     g_halted          = false;    // total-loss limit hit: no more trading
datetime g_streak[];                   // close times of the current run of consecutive losing closes
int      g_dd_scaled = 0, g_dd_skipped = 0, g_day_soft_scaled = 0, g_day_soft_skipped = 0;
int      g_or_scaled = 0, g_or_skipped = 0, g_streak_scaled = 0;
string   g_dd_tfs[];                   // parsed DdThrottleTfs
datetime g_last_deal_scan  = 0;        // history scan cursor for the streak throttle
string   g_last_request    = "";       // last request line answered (GOVERNOR)
long     g_magic           = 0;        // effective magic for trade management / limits

// standalone management records: one per plan (ticket of the position + ladder state)
struct LUPlan
  {
   ulong    pos_ticket;       // position ticket (0 = still pending)
   ulong    ord_ticket;       // pending order ticket
   int      side;             // +1 buy / -1 sell
   double   entry, sl, risk;  // 1R in price
   double   tps[8];
   double   fracs[8];
   int      n_legs;
   int      legs_closed;
   double   lots_total;
   double   lots_leg[8];
   datetime placed;
   int      placed_bar;       // bar index of ZoneTf at placement (for MaxPendingBars)
   double   dd_scale;         // v16c multiplier applied (for the log)
   bool     active;
  };
LUPlan   g_plans[];
double   g_tp_levels[8];
double   g_tp_fracs[8];
double   g_sl_after[8];       // NaN = "x" (leave)
int      g_n_tp = 0;

//--------------------------------------------------------------------
// small helpers
//--------------------------------------------------------------------
string ServerDay(datetime t = 0)
  {
   if(t == 0) t = TimeTradeServer();
   if(t == 0) t = TimeCurrent();
   MqlDateTime dt; TimeToStruct(t, dt);
   return StringFormat("%04d.%02d.%02d", dt.year, dt.mon, dt.day);
  }

int SplitPipe(const string s, string &out[])
  {
   ArrayResize(out, 0);
   if(StringLen(s) == 0) return 0;
   string parts[];
   int n = StringSplit(s, '|', parts);
   for(int i = 0; i < n; i++)
     {
      string p = parts[i];
      StringTrimLeft(p); StringTrimRight(p);
      if(StringLen(p) > 0) { int k = ArraySize(out); ArrayResize(out, k + 1); out[k] = p; }
     }
   return ArraySize(out);
  }

bool TfInScope(const string tf)
  {
   int n = ArraySize(g_dd_tfs);
   if(n == 0) return true;                         // "" = every timeframe
   for(int i = 0; i < n; i++) if(g_dd_tfs[i] == tf) return true;
   return false;
  }

string TfName(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M5:  return "M5";
      case PERIOD_M10: return "M10";
      case PERIOD_M15: return "M15";
      case PERIOD_M20: return "M20";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      default:         return StringSubstr(EnumToString(tf), 7);
     }
  }

double RoundVolumeDown(double v)
  {
   double step = g_sym.LotsStep(), vmin = g_sym.LotsMin(), vmax = g_sym.LotsMax();
   if(step <= 0) step = 0.01;
   double steps = MathFloor(v / step + 1e-9);
   double out = steps * step;
   if(out > vmax) out = vmax;
   if(out < vmin) return 0.0;
   return NormalizeDouble(out, 8);
  }

// $ lost per 1.0 lot per 1.0 price unit (contract size for XAUUSD = 100)
double UsdPerPriceUnitPerLot()
  {
   double tick_value = g_sym.TickValue();
   double tick_size  = g_sym.TickSize();
   if(tick_size <= 0) return g_sym.ContractSize();
   return tick_value / tick_size;
  }

double CurBasis(ENUM_DD_BASIS b) { return (b == DD_EQUITY) ? g_acc.Equity() : g_acc.Balance(); }

//--------------------------------------------------------------------
// STATE persistence (Common\Files so a terminal restart inside a drawdown keeps throttling = trader_state.json)
//--------------------------------------------------------------------
void SaveState()
  {
   int h = FileOpen(StateFile, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE) return;
   FileWrite(h, "v16c", DoubleToString(g_start_balance, 2), DoubleToString(g_peak, 2), g_day, DoubleToString(g_day_start, 2),
             g_daily_halt_day, (g_halted ? "1" : "0"), IntegerToString(g_dd_scaled), IntegerToString(g_dd_skipped),
             IntegerToString(g_day_soft_scaled), IntegerToString(g_day_soft_skipped), IntegerToString(g_or_scaled),
             IntegerToString(g_or_skipped), IntegerToString(g_streak_scaled));
   FileClose(h);
  }

void LoadState()
  {
   int h = FileOpen(StateFile, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE) return;
   string line = FileReadString(h);
   FileClose(h);
   string f[];
   if(StringSplit(line, '\t', f) < 7 || f[0] != "v16c") return;
   g_start_balance  = StringToDouble(f[1]);
   g_peak           = StringToDouble(f[2]);
   g_day            = f[3];
   g_day_start      = StringToDouble(f[4]);
   g_daily_halt_day = f[5];
   g_halted         = (f[6] == "1");
   if(ArraySize(f) >= 14)
     {
      g_dd_scaled = (int)StringToInteger(f[7]);  g_dd_skipped = (int)StringToInteger(f[8]);
      g_day_soft_scaled = (int)StringToInteger(f[9]); g_day_soft_skipped = (int)StringToInteger(f[10]);
      g_or_scaled = (int)StringToInteger(f[11]); g_or_skipped = (int)StringToInteger(f[12]);
      g_streak_scaled = (int)StringToInteger(f[13]);
     }
   PrintFormat("[v16c] state restored: peak %.2f day %s day_start %.2f halted %s daily_halt_day '%s'",
               g_peak, g_day, g_day_start, (g_halted ? "yes" : "no"), g_daily_halt_day);
  }

//--------------------------------------------------------------------
// RISK CORE  (identical formulas to PortfolioSimulator / trader.py)
//--------------------------------------------------------------------
// running peak of the dd basis - called on every tick (the sim updates it every minute, the bot every loop)
void UpdatePeak()
  {
   double cur = CurBasis(DdBasis);
   if(cur > g_peak) { g_peak = cur; }
  }

// drawdown from the peak in % (>= 0)
double DdNow()
  {
   if(g_peak <= 0) return 0.0;
   double cur = CurBasis(DdBasis);
   return MathMax(0.0, 100.0 * (1.0 - cur / g_peak));
  }

// == PortfolioSimulator.dd_throttle_scale / Trader.dd_throttle_scale
double DdThrottleScaleFor(double dd_pct)
  {
   if(DdThrottlePct <= 0 || dd_pct <= DdThrottlePct) return 1.0;
   if(DdThrottleRamp > 0)
     {
      double f = MathMin(1.0, (dd_pct - DdThrottlePct) / DdThrottleRamp);
      return 1.0 - f * (1.0 - DdThrottleScale);
     }
   return DdThrottleScale;
  }

// day rollover: day_start = equity at the first look of the new server day (sim: balance + floating at the rollover)
void RollDay()
  {
   string d = ServerDay();
   if(g_day != d || g_day_start <= 0)
     {
      g_day = d;
      g_day_start = g_acc.Equity();
      g_daily_halt_day = "";                       // a new server day: trading allowed again
      SaveState();
     }
  }

// sum over open legs of max(0, entry - stop) x lots x usd/unit  (BE legs or better = 0)  [+ pending initial risk]
double OpenRiskUsd(bool include_pending)
  {
   double tot = 0.0, upu = UsdPerPriceUnitPerLot();
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol) continue;
      if(g_magic != 0 && g_pos.Magic() != g_magic) continue;
      double sl = g_pos.StopLoss();
      if(sl <= 0) { tot += g_pos.Volume() * upu * g_sym.Ask() * 0.02; continue; }   // no stop: 2 % of notional as a guard
      double sgn = (g_pos.PositionType() == POSITION_TYPE_BUY) ? 1.0 : -1.0;
      tot += MathMax(0.0, sgn * (g_pos.PriceOpen() - sl)) * g_pos.Volume() * upu;
     }
   if(include_pending)
      for(int i = OrdersTotal() - 1; i >= 0; i--)
        {
         if(!g_ord.SelectByIndex(i)) continue;
         if(g_ord.Symbol() != _Symbol) continue;
         if(g_magic != 0 && g_ord.Magic() != g_magic) continue;
         if(g_ord.StopLoss() <= 0) continue;
         tot += MathAbs(g_ord.PriceOpen() - g_ord.StopLoss()) * g_ord.VolumeCurrent() * upu;
        }
   return tot;
  }

int CountOpenPlans()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) && g_pos.Symbol() == _Symbol && (g_magic == 0 || g_pos.Magic() == g_magic)) n++;
   return n;
  }

int CountPending()
  {
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
      if(g_ord.SelectByIndex(i) && g_ord.Symbol() == _Symbol && (g_magic == 0 || g_ord.Magic() == g_magic)) n++;
   return n;
  }

// loss-streak state from the closed deals (same loss definition as the martingale: r_net <= -mart_loss_r)
void UpdateStreakFromHistory()
  {
   if(StreakN <= 0) return;
   datetime from = (g_last_deal_scan == 0) ? TimeCurrent() - (int)(StreakDays * 86400) : g_last_deal_scan;
   if(!HistorySelect(from, TimeCurrent() + 60)) return;
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if(HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      if(g_magic != 0 && HistoryDealGetInteger(tk, DEAL_MAGIC) != g_magic) continue;
      if(HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_OUT && HistoryDealGetInteger(tk, DEAL_ENTRY) != DEAL_ENTRY_OUT_BY) continue;
      datetime t = (datetime)HistoryDealGetInteger(tk, DEAL_TIME);
      if(t <= g_last_deal_scan) continue;
      double net = HistoryDealGetDouble(tk, DEAL_PROFIT) + HistoryDealGetDouble(tk, DEAL_COMMISSION) + HistoryDealGetDouble(tk, DEAL_SWAP);
      // r_net needs the plan's risk money: approximate with the deal's |open - sl| x volume (sl from the position's history)
      double vol = HistoryDealGetDouble(tk, DEAL_VOLUME);
      double sl = HistoryDealGetDouble(tk, DEAL_SL), px = HistoryDealGetDouble(tk, DEAL_PRICE);
      double risk_money = (sl > 0) ? MathAbs(px - sl) * vol * UsdPerPriceUnitPerLot() : 0.0;
      double r = (risk_money > 0) ? net / risk_money : (net < 0 ? -1.0 : (net > 0 ? 1.0 : 0.0));
      if(r <= -StreakLossR)
        {
         // keep only losses within StreakDays, then append
         datetime keep[]; ArrayResize(keep, 0);
         for(int k = 0; k < ArraySize(g_streak); k++)
            if((double)(t - g_streak[k]) <= StreakDays * 86400.0) { int m = ArraySize(keep); ArrayResize(keep, m + 1); keep[m] = g_streak[k]; }
         int m = ArraySize(keep); ArrayResize(keep, m + 1); keep[m] = t;
         ArrayResize(g_streak, ArraySize(keep)); for(int k = 0; k < ArraySize(keep); k++) g_streak[k] = keep[k];
        }
      else if(r > 0) ArrayResize(g_streak, 0);
      g_last_deal_scan = t;
     }
  }

//--------------------------------------------------------------------
// THE v16c DECISION for one new plan  (== PortfolioSimulator._apply_v16c / Trader._apply_v16c)
// returns the multiplier to apply on top of the plan's own risk_scale; 0 = skip (reason filled)
//--------------------------------------------------------------------
double DecideMultiplier(const string tf, const double entry, const double sl, const double risk_scale_in, const bool grid_leg,
                        string &reason)
  {
   reason = "";
   if(g_halted)                 { reason = "halted (total loss limit)"; return 0.0; }
   if(g_daily_halt_day != "" && g_daily_halt_day == ServerDay()) { reason = "daily loss limit"; return 0.0; }
   if(grid_leg) return 1.0;                                      // grid deep legs are never throttled
   double f = 1.0;
   double dd = DdNow();
   double equity = g_acc.Equity();
   double base = (SizeOn == DD_EQUITY) ? equity : g_acc.Balance();
   // (1) drawdown throttle
   if(DdThrottlePct > 0 && TfInScope(tf))
     {
      double s = DdThrottleScaleFor(dd);
      if(s < 1.0)
        {
         if(s <= 0) { g_dd_skipped++; reason = StringFormat("dd throttle (%.2f %% below peak %.2f)", dd, g_peak); SaveState(); return 0.0; }
         f *= s; g_dd_scaled++;
         reason = StringFormat("drawdown %.2f %% below peak %.2f -> x%.3f", dd, g_peak, s);
        }
     }
   // (2) day soft cap
   if(DaySoftLossPct > 0 && g_day_start > 0 && equity <= g_day_start * (1.0 - DaySoftLossPct / 100.0))
     {
      if(DaySoftScale <= 0) { g_day_soft_skipped++; reason = "day soft cap"; SaveState(); return 0.0; }
      f *= DaySoftScale; g_day_soft_scaled++;
      reason += StringFormat("%sday soft cap -> x%.2f", (reason == "" ? "" : "; "), DaySoftScale);
     }
   // (3) loss-streak throttle
   if(StreakN > 0 && ArraySize(g_streak) >= StreakN)
     {
      f *= StreakScale; g_streak_scaled++;
      reason += StringFormat("%sstreak %d -> x%.2f", (reason == "" ? "" : "; "), ArraySize(g_streak), StreakScale);
     }
   // (4) open-risk cap (after every other multiplier; "fit" scales the plan into the remaining budget)
   if(MaxOpenRiskPct > 0)
     {
      double used = OpenRiskUsd(OpenRiskPending);
      double budget = base * MaxOpenRiskPct / 100.0 - used;
      double rs = (risk_scale_in > 0 ? risk_scale_in : 1.0) * f;
      double own = base * RiskPct / 100.0 * rs;
      if(own > budget + 1e-9)
        {
         double per_unit = UsdPerPriceUnitPerLot() * MathAbs(entry - sl);
         double fit_lots = (budget > 0 && per_unit > 0) ? RoundVolumeDown(budget / per_unit) : 0.0;
         if(OpenRiskMode == OR_SKIP || fit_lots < g_sym.LotsMin())
           {
            g_or_skipped++; reason = StringFormat("open risk cap (%.2f %% used)", 100.0 * used / base); SaveState(); return 0.0;
           }
         double g = budget / own;
         f *= g; g_or_scaled++;
         reason += StringFormat("%sopen risk %.2f %% used -> x%.3f", (reason == "" ? "" : "; "), 100.0 * used / base, g);
        }
     }
   if(f != 1.0) SaveState();
   return f;
  }

// lots for a plan: RiskPct % of base x multipliers between entry and stop, rounded down to the broker step
double LotsFor(const double entry, const double sl, const double mult)
  {
   double base = (SizeOn == DD_EQUITY) ? g_acc.Equity() : g_acc.Balance();
   double risk_money = base * RiskPct / 100.0 * mult;
   double per_unit = UsdPerPriceUnitPerLot() * MathAbs(entry - sl);
   if(per_unit <= 0) return 0.0;
   return RoundVolumeDown(risk_money / per_unit);
  }

//--------------------------------------------------------------------
// HARD LIMITS (v10): total -> flatten + halt; daily -> flatten + no new orders until the next server day
//--------------------------------------------------------------------
void FlattenAll(const string why)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol) continue;
      if(g_magic != 0 && g_pos.Magic() != g_magic) continue;
      g_trade.SetExpertMagicNumber(g_pos.Magic());
      if(!g_trade.PositionClose(g_pos.Ticket(), Slippage))
         PrintFormat("[v16c] %s: close #%I64u FAILED %d", why, g_pos.Ticket(), g_trade.ResultRetcode());
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      if(!g_ord.SelectByIndex(i)) continue;
      if(g_ord.Symbol() != _Symbol) continue;
      if(g_magic != 0 && g_ord.Magic() != g_magic) continue;
      g_trade.OrderDelete(g_ord.Ticket());
     }
   for(int k = 0; k < ArraySize(g_plans); k++) g_plans[k].active = false;
  }

void CheckHardLimits()
  {
   double equity = g_acc.Equity();
   if(MaxTotalLossPct > 0 && !g_halted && g_start_balance > 0 && equity <= g_start_balance * (1.0 - MaxTotalLossPct / 100.0))
     {
      PrintFormat("[v16c] TOTAL LOSS LIMIT: equity %.2f <= %.1f %% of start balance %.2f -> flatten + HALT", equity, 100 - MaxTotalLossPct, g_start_balance);
      FlattenAll("halt");
      g_halted = true;
      SaveState();
      return;
     }
   if(MaxDailyLossPct > 0 && g_daily_halt_day == "" && g_day_start > 0 && equity <= g_day_start * (1.0 - MaxDailyLossPct / 100.0))
     {
      PrintFormat("[v16c] DAILY LOSS LIMIT: equity %.2f <= %.1f %% of day start %.2f -> flatten, no new orders today", equity, 100 - MaxDailyLossPct, g_day_start);
      FlattenAll("daily_halt");
      g_daily_halt_day = ServerDay();
      SaveState();
     }
  }
