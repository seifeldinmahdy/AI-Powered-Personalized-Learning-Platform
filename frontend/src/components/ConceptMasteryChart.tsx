import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import type { ConceptMasteryEntry } from '../services/progress';

const TREND_COLOR: Record<string, string> = {
    up: '#22c55e',
    flat: '#f59e0b',
    down: '#ef4444',
};

interface Props {
    data: ConceptMasteryEntry[];
}

export function ConceptMasteryChart({ data }: Props) {
    if (data.length === 0) return null;

    const chartData = data.map((entry) => ({
        name: entry.label.length > 14 ? `${entry.label.slice(0, 12)}…` : entry.label,
        score: Math.round(entry.score * 100),
        trend: entry.trend,
        fullLabel: entry.label,
        evidence: entry.evidence,
    }));

    return (
        <div>
            <h3 className="mb-4">Concept Mastery</h3>
            <div className="bg-card rounded-xl p-5 border border-border shadow-sm">
                <ResponsiveContainer width="100%" height={190}>
                    <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 36, left: 0 }}>
                        <XAxis
                            dataKey="name"
                            tick={{ fontSize: 11 }}
                            angle={-35}
                            textAnchor="end"
                            interval={0}
                        />
                        <YAxis
                            domain={[0, 100]}
                            tickFormatter={(v: number) => `${v}%`}
                            tick={{ fontSize: 11 }}
                            width={36}
                        />
                        <Tooltip
                            formatter={(value: number, _: string, props: { payload?: { fullLabel?: string; evidence?: number } }) => [
                                `${value}% (${props.payload?.evidence ?? 0} attempts)`,
                                props.payload?.fullLabel ?? '',
                            ]}
                        />
                        <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                            {chartData.map((entry, index) => (
                                <Cell key={index} fill={TREND_COLOR[entry.trend] ?? '#6366f1'} />
                            ))}
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
                <div className="flex items-center gap-4 mt-1 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-green-500 inline-block" /> Improving
                    </span>
                    <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" /> Stable
                    </span>
                    <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Declining
                    </span>
                </div>
            </div>
        </div>
    );
}
