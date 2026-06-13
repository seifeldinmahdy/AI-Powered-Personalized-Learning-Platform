import { Award, Download, Loader2, CheckCircle2 } from 'lucide-react';
import type { Certificate as CertificateData } from '../services/certificate';

interface Props {
    data: CertificateData;
    onDownload: () => void;
    downloading?: boolean;
}

/** On-page styled, printable certificate. PDF is generated server-side on download. */
export function Certificate({ data, onDownload, downloading }: Props) {
    return (
        <div className="space-y-4">
            <div className="relative overflow-hidden rounded-2xl border-2 border-primary/40 bg-gradient-to-br from-primary/5 via-card to-secondary/5 p-8 text-center shadow-sm">
                <div className="absolute inset-3 rounded-xl border border-primary/20 pointer-events-none" />
                <div className="relative space-y-4">
                    <div className="mx-auto w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center">
                        <Award className="w-7 h-7 text-primary" />
                    </div>
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                        Certificate of Completion
                    </p>
                    <p className="text-sm text-muted-foreground">This certifies that</p>
                    <h2 className="text-2xl font-bold text-foreground">{data.student_name}</h2>
                    <p className="text-sm text-muted-foreground">has successfully completed</p>
                    <h3 className="text-lg font-semibold text-foreground">{data.course_title}</h3>

                    {data.clos_attained.length > 0 && (
                        <div className="mx-auto max-w-md text-left pt-2">
                            <p className="text-xs font-semibold text-primary mb-2 text-center">
                                Learning outcomes attained
                            </p>
                            <ul className="space-y-1">
                                {data.clos_attained.map((clo) => (
                                    <li key={clo.code} className="flex items-start gap-2 text-sm">
                                        <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
                                        <span>
                                            <span className="font-medium">{clo.code}:</span> {clo.text}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    <div className="flex items-center justify-between pt-4 text-xs text-muted-foreground">
                        <span>{data.completion_date ? `Date: ${data.completion_date}` : ''}</span>
                        {data.score !== null && <span>Capstone score: {data.score}%</span>}
                        <span className="font-mono">{data.verification_id}</span>
                    </div>
                </div>
            </div>

            <button
                onClick={onDownload}
                disabled={downloading}
                className="flex items-center gap-2 mx-auto bg-primary text-primary-foreground px-5 py-2.5 rounded-xl text-sm font-medium hover:opacity-90 disabled:opacity-50"
            >
                {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                Download PDF
            </button>
        </div>
    );
}
