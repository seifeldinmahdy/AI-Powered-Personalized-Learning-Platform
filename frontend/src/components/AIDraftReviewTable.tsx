import { useState } from 'react';
import { Check, Edit, Trash2, Plus, X, Save, Loader2 } from 'lucide-react';

export type RowStatus = 'pending' | 'approved' | 'edited';

export interface Column<T extends object> {
    key: keyof T & string;
    header: string;
    editable?: boolean;
    width?: string;
    renderCell?: (value: unknown, row: T) => React.ReactNode;
}

interface Props<T extends object> {
    columns: Column<T>[];
    initialRows: T[];
    onSave: (rows: T[]) => Promise<void>;
    onCancel?: () => void;
    emptyRow: T;
}

type Row<T> = T & { _status: RowStatus; _localId: string };

function genId() {
    return Math.random().toString(36).slice(2);
}

const STATUS_BADGE: Record<RowStatus, string> = {
    pending: 'bg-amber-100 text-amber-700',
    approved: 'bg-green-100 text-green-700',
    edited: 'bg-blue-100 text-blue-700',
};

export function AIDraftReviewTable<T extends object>({
    columns,
    initialRows,
    onSave,
    onCancel,
    emptyRow,
}: Props<T>) {
    const [rows, setRows] = useState<Row<T>[]>(() =>
        initialRows.map((r) => ({ ...r, _status: 'pending' as RowStatus, _localId: genId() })),
    );
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editBuffer, setEditBuffer] = useState<Record<string, unknown>>({});
    const [saving, setSaving] = useState(false);

    const startEdit = (row: Row<T>) => {
        setEditingId(row._localId);
        setEditBuffer({ ...row } as Record<string, unknown>);
    };

    const commitEdit = (localId: string) => {
        setRows((prev) =>
            prev.map((r) =>
                r._localId === localId
                    ? { ...r, ...editBuffer, _status: 'edited' as RowStatus }
                    : r,
            ),
        );
        setEditingId(null);
        setEditBuffer({});
    };

    const cancelEdit = () => {
        setEditingId(null);
        setEditBuffer({});
    };

    const approve = (localId: string) => {
        setRows((prev) =>
            prev.map((r) =>
                r._localId === localId ? { ...r, _status: 'approved' as RowStatus } : r,
            ),
        );
    };

    const remove = (localId: string) => {
        setRows((prev) => prev.filter((r) => r._localId !== localId));
    };

    const addRow = () => {
        const newRow: Row<T> = { ...emptyRow, _status: 'edited' as RowStatus, _localId: genId() };
        setRows((prev) => [...prev, newRow]);
        setEditingId(newRow._localId);
        setEditBuffer({ ...emptyRow } as Record<string, unknown>);
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            const toSave = rows
                .filter((r) => r._status === 'approved' || r._status === 'edited')
                .map(({ _status: _s, _localId: _id, ...rest }) => rest as unknown as T);
            await onSave(toSave);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-4">
            <div className="overflow-x-auto rounded-xl border border-border">
                <table className="w-full text-sm">
                    <thead className="bg-muted/50">
                        <tr>
                            {columns.map((col) => (
                                <th
                                    key={col.key}
                                    className={`px-4 py-3 text-left font-semibold text-muted-foreground ${col.width ?? ''}`}
                                >
                                    {col.header}
                                </th>
                            ))}
                            <th className="px-4 py-3 text-left font-semibold text-muted-foreground w-28">
                                Status
                            </th>
                            <th className="px-4 py-3 w-28" />
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row) => {
                            const isEditing = editingId === row._localId;
                            return (
                                <tr
                                    key={row._localId}
                                    className="border-t border-border hover:bg-muted/30 transition-colors"
                                >
                                    {columns.map((col) => (
                                        <td key={col.key} className="px-4 py-3 align-top">
                                            {isEditing && col.editable ? (
                                                <input
                                                    className="w-full border border-border rounded-lg px-2 py-1 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
                                                    value={String(editBuffer[col.key] ?? '')}
                                                    onChange={(e) =>
                                                        setEditBuffer((prev) => ({
                                                            ...prev,
                                                            [col.key]: e.target.value,
                                                        }))
                                                    }
                                                />
                                            ) : col.renderCell ? (
                                                col.renderCell(row[col.key], row as unknown as T)
                                            ) : (
                                                <span className="text-foreground">
                                                    {String(row[col.key] ?? '')}
                                                </span>
                                            )}
                                        </td>
                                    ))}
                                    <td className="px-4 py-3 align-top">
                                        <span
                                            className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${STATUS_BADGE[row._status]}`}
                                        >
                                            {row._status}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 align-top">
                                        <div className="flex items-center gap-1 justify-end">
                                            {isEditing ? (
                                                <>
                                                    <button
                                                        onClick={() => commitEdit(row._localId)}
                                                        className="p-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20"
                                                        title="Save edit"
                                                    >
                                                        <Check size={13} />
                                                    </button>
                                                    <button
                                                        onClick={cancelEdit}
                                                        className="p-1.5 rounded-lg bg-muted text-muted-foreground hover:bg-muted/80"
                                                        title="Cancel"
                                                    >
                                                        <X size={13} />
                                                    </button>
                                                </>
                                            ) : (
                                                <>
                                                    {row._status !== 'approved' && (
                                                        <button
                                                            onClick={() => approve(row._localId)}
                                                            className="p-1.5 rounded-lg bg-green-50 text-green-600 hover:bg-green-100"
                                                            title="Approve"
                                                        >
                                                            <Check size={13} />
                                                        </button>
                                                    )}
                                                    <button
                                                        onClick={() => startEdit(row)}
                                                        className="p-1.5 rounded-lg hover:bg-muted/60 text-muted-foreground"
                                                        title="Edit"
                                                    >
                                                        <Edit size={13} />
                                                    </button>
                                                    <button
                                                        onClick={() => remove(row._localId)}
                                                        className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive"
                                                        title="Delete"
                                                    >
                                                        <Trash2 size={13} />
                                                    </button>
                                                </>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                        {rows.length === 0 && (
                            <tr>
                                <td
                                    colSpan={columns.length + 2}
                                    className="px-4 py-8 text-center text-muted-foreground text-sm"
                                >
                                    No drafts. Add a row manually or generate new ones.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            <div className="flex items-center justify-between">
                <button
                    onClick={addRow}
                    className="flex items-center gap-2 px-3 py-2 rounded-xl border border-border text-sm text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                >
                    <Plus size={14} /> Add Row
                </button>
                <div className="flex items-center gap-2">
                    {onCancel && (
                        <button
                            onClick={onCancel}
                            className="px-4 py-2 rounded-xl text-sm text-muted-foreground hover:bg-muted/60 transition-colors"
                        >
                            Cancel
                        </button>
                    )}
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors"
                    >
                        {saving ? (
                            <Loader2 size={14} className="animate-spin" />
                        ) : (
                            <Save size={14} />
                        )}
                        Save Approved
                    </button>
                </div>
            </div>
        </div>
    );
}
