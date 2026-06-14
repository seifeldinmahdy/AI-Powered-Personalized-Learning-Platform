import { useState } from "react";
import { useNavigate } from "react-router";
import { UserPlus, ArrowLeft, Loader2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import api from "../../services/api";

export default function StudentCreate() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    username: "",
    email: "",
    password: "",
    confirmPassword: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.username.trim()) e.username = "Username is required";
    if (!form.email.trim()) e.email = "Email is required";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
      e.email = "Invalid email format";
    if (!form.password) e.password = "Password is required";
    else if (form.password.length < 8)
      e.password = "Password must be at least 8 characters";
    if (form.password !== form.confirmPassword)
      e.confirmPassword = "Passwords do not match";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!validate()) return;
    setSubmitting(true);
    try {
      await api.post("/users/admin-create-student/", {
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
      });
      toast.success(`Student "${form.username}" created successfully`);
      navigate("/admin/students");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data
          ?.error || "Failed to create student";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const set = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((f) => ({ ...f, [field]: e.target.value }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[field];
      return next;
    });
  };

  return (
    <div>
      {/* Back link */}
      <button
        onClick={() => navigate("/admin/students")}
        className="flex items-center gap-2 mb-6 text-sm font-medium transition-colors"
        style={{ color: "var(--admin-muted)" }}
        onMouseEnter={(e) =>
          (e.currentTarget.style.color = "var(--admin-accent)")
        }
        onMouseLeave={(e) =>
          (e.currentTarget.style.color = "var(--admin-muted)")
        }
      >
        <ArrowLeft size={16} /> Back to Students
      </button>

      <div className="max-w-xl">
        <div className="flex items-center gap-3 mb-8">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ background: "var(--admin-accent)", color: "var(--admin-ink)" }}
          >
            <UserPlus size={22} />
          </div>
          <div>
            <h1 className="admin-heading" id="student-create-title">
              Create Student
            </h1>
            <p className="admin-subheading">Add a new student account</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="admin-card p-8 space-y-6">
          {/* Username */}
          <div>
            <label
              className="block text-sm font-semibold mb-2"
              style={{ color: "var(--admin-ink)" }}
            >
              Username
            </label>
            <input
              id="student-username"
              type="text"
              value={form.username}
              onChange={set("username")}
              className="admin-input w-full"
              placeholder="e.g. john_doe"
              autoFocus
            />
            {errors.username && (
              <p className="flex items-center gap-1 mt-1 text-xs" style={{ color: "var(--admin-red, #ff4444)" }}>
                <AlertCircle size={12} /> {errors.username}
              </p>
            )}
          </div>

          {/* Email */}
          <div>
            <label
              className="block text-sm font-semibold mb-2"
              style={{ color: "var(--admin-ink)" }}
            >
              Email
            </label>
            <input
              id="student-email"
              type="email"
              value={form.email}
              onChange={set("email")}
              className="admin-input w-full"
              placeholder="john@example.com"
            />
            {errors.email && (
              <p className="flex items-center gap-1 mt-1 text-xs" style={{ color: "var(--admin-red, #ff4444)" }}>
                <AlertCircle size={12} /> {errors.email}
              </p>
            )}
          </div>

          {/* Password */}
          <div>
            <label
              className="block text-sm font-semibold mb-2"
              style={{ color: "var(--admin-ink)" }}
            >
              Password
            </label>
            <input
              id="student-password"
              type="password"
              value={form.password}
              onChange={set("password")}
              className="admin-input w-full"
              placeholder="Min 8 characters"
            />
            {errors.password && (
              <p className="flex items-center gap-1 mt-1 text-xs" style={{ color: "var(--admin-red, #ff4444)" }}>
                <AlertCircle size={12} /> {errors.password}
              </p>
            )}
          </div>

          {/* Confirm Password */}
          <div>
            <label
              className="block text-sm font-semibold mb-2"
              style={{ color: "var(--admin-ink)" }}
            >
              Confirm Password
            </label>
            <input
              id="student-confirm-password"
              type="password"
              value={form.confirmPassword}
              onChange={set("confirmPassword")}
              className="admin-input w-full"
              placeholder="Re-enter password"
            />
            {errors.confirmPassword && (
              <p className="flex items-center gap-1 mt-1 text-xs" style={{ color: "var(--admin-red, #ff4444)" }}>
                <AlertCircle size={12} /> {errors.confirmPassword}
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 pt-4">
            <button
              type="submit"
              disabled={submitting}
              className="admin-btn admin-btn-primary flex items-center gap-2"
              id="student-create-submit"
            >
              {submitting ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <UserPlus size={16} />
              )}
              {submitting ? "Creating..." : "Create Student"}
            </button>
            <button
              type="button"
              onClick={() => navigate("/admin/students")}
              className="admin-btn admin-btn-secondary"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
