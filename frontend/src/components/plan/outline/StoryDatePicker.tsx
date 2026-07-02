import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DAYS_OF_WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const DAYS_OF_WEEK_FULL = [
  "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
];

function getOrdinal(n: number): string {
  const v = n % 100;
  const s = ["th", "st", "nd", "rd"];
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function formatDate(year: number | null, month: number, day: number): string {
  const dow = DAYS_OF_WEEK_FULL[new Date(year ?? 2001, month, day).getDay()];
  let s = `${dow}, ${MONTHS[month]} ${getOrdinal(day)}`;
  if (year) s += `, ${year}`;
  return s;
}

export function parseDateString(s: string): {
  year: number | null;
  month: number | null;
  day: number | null;
} {
  const result = { year: null as number | null, month: null as number | null, day: null as number | null };
  if (!s?.trim()) return result;

  const cleaned = s.replace(/(\d+)(st|nd|rd|th)/gi, "$1");

  // "Saturday, October 31" or "Saturday, October 31, 2024"
  const withDow = cleaned.match(/^(\w+),\s+(\w+)\s+(\d+)(?:,\s+(\d{4}))?$/);
  if (withDow) {
    const monthIdx = MONTHS.findIndex((m) => m.toLowerCase() === withDow[2].toLowerCase());
    if (monthIdx >= 0) {
      result.month = monthIdx;
      result.day = parseInt(withDow[3]);
      result.year = withDow[4] ? parseInt(withDow[4]) : null;
    }
    return result;
  }

  // "October 31" or "October 31, 2024"
  const withoutDow = cleaned.match(/^(\w+)\s+(\d+)(?:,\s+(\d{4}))?$/);
  if (withoutDow) {
    const monthIdx = MONTHS.findIndex((m) => m.toLowerCase() === withoutDow[1].toLowerCase());
    if (monthIdx >= 0) {
      result.month = monthIdx;
      result.day = parseInt(withoutDow[2]);
      result.year = withoutDow[3] ? parseInt(withoutDow[3]) : null;
    }
  }
  return result;
}

interface StoryDatePickerProps {
  value: string;
  onChange: (value: string) => void;
}

export default function StoryDatePicker({ value, onChange }: StoryDatePickerProps) {
  const parsed = parseDateString(value);

  const today = new Date();
  const initMonth = parsed.month ?? today.getMonth();
  const initYear = parsed.year ?? today.getFullYear();

  const [viewMonth, setViewMonth] = useState(initMonth); // 0-indexed
  const [viewYear, setViewYear] = useState(initYear);
  const [selectedDay, setSelectedDay] = useState<number | null>(parsed.day ?? null);
  const [selectedMonth, setSelectedMonth] = useState<number | null>(parsed.month ?? null); // 0-indexed
  const [selectedYear, setSelectedYear] = useState<number | null>(parsed.year ?? null);
  const [editingYear, setEditingYear] = useState(false);
  const [yearInput, setYearInput] = useState(String(initYear));

  const firstDayOfMonth = new Date(viewYear, viewMonth, 1).getDay();
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear((y) => y - 1); }
    else setViewMonth((m) => m - 1);
  };

  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear((y) => y + 1); }
    else setViewMonth((m) => m + 1);
  };

  const selectDay = (day: number) => {
    setSelectedDay(day);
    setSelectedMonth(viewMonth);
    setSelectedYear(viewYear);
    onChange(formatDate(viewYear, viewMonth, day));
  };

  const isSelected = (day: number) =>
    day === selectedDay && viewMonth === selectedMonth && viewYear === selectedYear;

  const isToday = (day: number) =>
    day === today.getDate() && viewMonth === today.getMonth() && viewYear === today.getFullYear();

  // Build calendar grid cells
  const cells: (number | null)[] = [
    ...Array(firstDayOfMonth).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  // Pad to full rows
  while (cells.length % 7 !== 0) cells.push(null);

  return (
    <div className="w-56 select-none">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <button
          type="button"
          onClick={prevMonth}
          className="rounded p-0.5 text-ink-muted hover:text-ink-secondary hover:bg-surface-hover transition-colors"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>

        <div className="flex items-center gap-1.5 text-[11px] font-medium text-ink-primary">
          <span>{MONTHS[viewMonth]}</span>
          {editingYear ? (
            <input
              autoFocus
              type="number"
              value={yearInput}
              onChange={(e) => setYearInput(e.target.value)}
              onBlur={() => {
                const y = parseInt(yearInput);
                if (y > 0 && y < 10000) setViewYear(y);
                else setYearInput(String(viewYear));
                setEditingYear(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                if (e.key === "Escape") { setYearInput(String(viewYear)); setEditingYear(false); }
              }}
              className="w-14 rounded border border-accent/40 bg-surface px-1 py-0.5 text-[11px] text-center text-ink-primary focus:outline-none"
            />
          ) : (
            <button
              type="button"
              onClick={() => { setYearInput(String(viewYear)); setEditingYear(true); }}
              className="rounded px-1 py-0.5 text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors"
            >
              {viewYear}
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={nextMonth}
          className="rounded p-0.5 text-ink-muted hover:text-ink-secondary hover:bg-surface-hover transition-colors"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Day-of-week headers */}
      <div className="grid grid-cols-7 mb-1">
        {DAYS_OF_WEEK.map((d) => (
          <div key={d} className="text-center text-[9px] font-medium text-ink-muted/60 py-0.5">
            {d}
          </div>
        ))}
      </div>

      {/* Day grid */}
      <div className="grid grid-cols-7 gap-y-0.5">
        {cells.map((day, i) => (
          <div key={i} className="flex items-center justify-center">
            {day ? (
              <button
                type="button"
                onClick={() => selectDay(day)}
                className={[
                  "h-6 w-6 rounded-full text-[11px] transition-colors",
                  isSelected(day)
                    ? "bg-accent text-white font-medium"
                    : isToday(day)
                    ? "border border-accent/40 text-accent font-medium hover:bg-accent/10"
                    : "text-ink-secondary hover:bg-surface-hover",
                ].join(" ")}
              >
                {day}
              </button>
            ) : null}
          </div>
        ))}
      </div>

      {/* Selected date preview */}
      {selectedDay !== null && selectedMonth !== null && (
        <div className="mt-2 pt-2 border-t border-surface-border text-center text-[11px] text-accent/80">
          {formatDate(selectedYear, selectedMonth, selectedDay)}
        </div>
      )}
    </div>
  );
}
