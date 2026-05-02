import { Navigate, useParams } from "react-router";
import { useEffect, useState } from "react";
import { getEnrollments } from "../services/api";
import { Loader2 } from "lucide-react";

export default function RequirePathway({ children }: { children: React.ReactNode }) {
    const { courseId } = useParams<{ courseId: string }>();
    const [isPathwayReady, setIsPathwayReady] = useState<boolean | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let isMounted = true;

        async function checkEnrollment() {
            try {
                const res = await getEnrollments();
                const list = Array.isArray(res.data) ? res.data : res.data?.results || [];
                const enrollment = list.find((e: any) => e.course === Number(courseId));
                
                if (isMounted) {
                    if (enrollment && enrollment.is_pathway_ready) {
                        setIsPathwayReady(true);
                    } else {
                        setIsPathwayReady(false);
                    }
                }
            } catch (err) {
                if (isMounted) setIsPathwayReady(false);
            } finally {
                if (isMounted) setLoading(false);
            }
        }

        if (courseId) checkEnrollment();
        else setLoading(false);

        return () => { isMounted = false; };
    }, [courseId]);

    if (loading) {
        return (
            <div className="flex bg-background h-screen w-full items-center justify-center">
                <Loader2 size={40} className="animate-spin text-secondary" />
            </div>
        );
    }

    if (isPathwayReady === false) {
        return <Navigate to={`/courses/${courseId}/assessment`} replace />;
    }

    return <>{children}</>;
}
