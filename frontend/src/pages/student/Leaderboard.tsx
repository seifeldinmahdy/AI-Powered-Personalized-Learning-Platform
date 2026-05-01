import { useEffect, useState } from 'react';
import { Trophy, Flame, Star } from 'lucide-react';
import { toast } from 'sonner';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

interface LeaderboardEntry {
  rank: number;
  username: string;
  level: number;
  current_xp: number;
  current_streak: number;
}

interface LeaderboardData {
  top20: LeaderboardEntry[];
  current_user: LeaderboardEntry;
}

const rankStyle: Record<number, string> = {
  1: 'bg-yellow-400/20 border-yellow-400 text-yellow-600',
  2: 'bg-slate-300/20 border-slate-400 text-slate-500',
  3: 'bg-amber-600/20 border-amber-500 text-amber-700',
};

const rankLabel: Record<number, string> = {
  1: '🥇',
  2: '🥈',
  3: '🥉',
};

export default function Leaderboard() {
  const [data, setData] = useState<LeaderboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;
    fetch(`${API_URL}/users/leaderboard/`, {
      headers: { Authorization: `Token ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error('Failed to load leaderboard');
        return res.json();
      })
      .then(setData)
      .catch(() => toast.error('Could not load leaderboard'))
      .finally(() => setLoading(false));
  }, []);

  const currentUserInTop20 = data?.top20.some(
    (e) => e.username === data.current_user.username,
  );

  return (
    <div className="max-w-2xl mx-auto py-10 px-4">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20">
          <Trophy size={28} className="text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Leaderboard</h1>
          <p className="text-sm text-muted-foreground">Top 20 students by XP</p>
        </div>
      </div>

      {loading && (
        <div className="flex justify-center py-20">
          <div className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        </div>
      )}

      {!loading && data && (
        <div className="bg-card rounded-2xl border border-border shadow-sm overflow-hidden">
          {data.top20.map((entry) => {
            const isMe = entry.username === data.current_user.username;
            const special = rankStyle[entry.rank];
            return (
              <div
                key={entry.rank}
                className={`flex items-center gap-4 px-5 py-3 border-b border-border last:border-b-0 transition-colors ${
                  isMe ? 'bg-primary/5' : 'hover:bg-muted/40'
                } ${special ? 'border-l-4 ' + special.split(' ')[1] : ''}`}
              >
                <span className="w-8 text-center font-bold text-muted-foreground text-sm">
                  {rankLabel[entry.rank] ?? `#${entry.rank}`}
                </span>
                <div className="flex-1 min-w-0">
                  <span className={`font-semibold truncate ${isMe ? 'text-primary' : ''}`}>
                    {entry.username}
                    {isMe && <span className="ml-2 text-xs text-muted-foreground font-normal">(you)</span>}
                  </span>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Star size={11} className="text-secondary" />
                      Lv {entry.level}
                    </span>
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Flame size={11} className="text-orange-500" />
                      {entry.current_streak}d
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="font-bold text-sm">{entry.current_xp.toLocaleString()}</span>
                  <span className="text-xs text-muted-foreground ml-1">XP</span>
                </div>
              </div>
            );
          })}

          {!currentUserInTop20 && (
            <>
              <div className="px-5 py-2 text-center text-muted-foreground text-sm border-b border-border">
                · · ·
              </div>
              <div className="flex items-center gap-4 px-5 py-3 bg-primary/5 border-l-4 border-primary">
                <span className="w-8 text-center font-bold text-primary text-sm">
                  #{data.current_user.rank}
                </span>
                <div className="flex-1 min-w-0">
                  <span className="font-semibold text-primary truncate">
                    {data.current_user.username}
                    <span className="ml-2 text-xs text-muted-foreground font-normal">(you)</span>
                  </span>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Star size={11} className="text-secondary" />
                      Lv {data.current_user.level}
                    </span>
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Flame size={11} className="text-orange-500" />
                      {data.current_user.current_streak}d
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="font-bold text-sm">{data.current_user.current_xp.toLocaleString()}</span>
                  <span className="text-xs text-muted-foreground ml-1">XP</span>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
