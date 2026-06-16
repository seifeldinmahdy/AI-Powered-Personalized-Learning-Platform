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
    pending: 'admin-badge admin-badge-amber',
    approved: 'admin-badge admin-badge-green',
    edited: 'admin-badge admin-badge-blue',
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
            <div className="admin-card overflow-hidden">
                <table className="admin-table">
                    <thead>
                        <tr>
                            {columns.map((col) => (
                                <th
                                    key={col.key}
                                    className={col.width ?? ''}
                                >
                                    {col.header}
                                </th>
                            ))}
                            <th style={{ width: '7rem' }}>Status</th>
                            <th style={{ width: '7rem' }} />
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row) => {
                            const isEditing = editingId === row._localId;
                            return (
                                <tr key={row._localId}>
                                    {columns.map((col) => (
                                        <td key={col.key}>
                                            {isEditing && col.editable ? (
                                                <input
                                                    className="admin-input w-full"
                                                    style={{ padding: '6px 8px', fontSize: '14px' }}
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
                                                <span style={{ color: 'var(--admin-ink)' }}>
                                                    {String(row[col.key] ?? '')}
                                                </span>
                                            )}
                                        </td>
                                    ))}
                                    <td>
                                        <span
                                            className={STATUS_BADGE[row._status]}
                                            style={{ padding: '4px 8px', fontSize: '11px' }}
                                        >
                                            {row._status}
                                        </span>
                                    </td>
                                    <td>
                                        <div className="flex items-center gap-1 justify-end">
                                            {isEditing ? (
                                                <>
                                                    <button
                                                        onClick={() => commitEdit(row._localId)}
                                                        className="admin-btn admin-btn-icon"
                                                        style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}
                                                        title="Save edit"
                                                    >
                                                        <Check size={13} />
                                                    </button>
                                                    <button
                                                        onClick={cancelEdit}
                                                        className="admin-btn admin-btn-ghost admin-btn-icon"
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
                                                            className="admin-btn admin-btn-icon"
                                                            style={{ background: 'var(--admin-success-subtle, #dcfce7)', color: 'var(--admin-success)' }}
                                                            title="Approve"
                                                        >
                                                            <Check size={13} />
                                                        </button>
                                                    )}
                                                    <button
                                                        onClick={() => startEdit(row)}
                                                        className="admin-btn admin-btn-ghost admin-btn-icon"
                                                        title="Edit"
                                                    >
                                                        <Edit size={13} />
                                                    </button>
                                                    <button
                                                        onClick={() => remove(row._localId)}
                                                        className="admin-btn admin-btn-ghost-danger admin-btn-icon"
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
                                    className="text-center"
                                    style={{ color: 'var(--admin-ink-secondary)', padding: '32px' }}
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
                    className="admin-btn admin-btn-ghost admin-btn-sm"
                >
                    <Plus size={14} /> Add Row
                </button>
                <div className="flex items-center gap-2">
                    {onCancel && (
                        <button
                            onClick={onCancel}
                            className="admin-btn admin-btn-ghost admin-btn-sm"
                        >
                            Cancel
                        </button>
                    )}
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="admin-btn admin-btn-primary admin-btn-sm disabled:opacity-60"
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
