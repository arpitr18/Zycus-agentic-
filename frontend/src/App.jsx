import { useState, lazy, Suspense } from "react";
import {
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Ticket,
  BookOpen,
  ChartNoAxesCombined,
  Settings,
  Building2,
  LogOut,
  Menu,
  X,
  ShieldCheck,
  ArrowRight,
} from "lucide-react";
import { useAuth } from "./auth";
import { api } from "./api";
import { Button } from "./components/ui/button";
import { Loading, ErrorState } from "./components/shared";
const Overview=lazy(()=>import("./pages/Overview"));
const Tickets=lazy(()=>import("./pages/Tickets"));const TicketDetail=lazy(()=>import("./pages/Tickets").then(m=>({default:m.TicketDetail})));
const Investigation=lazy(()=>import("./pages/Investigation"));
const Knowledge=lazy(()=>import("./pages/Knowledge"));
const Analytics=lazy(()=>import("./pages/Analytics"));
const Admin=lazy(()=>import("./pages/Admin"));
const Accounts=lazy(()=>import("./pages/Accounts"));
function Guard({ manager = false, admin = false, children }) {
  const a = useAuth();
  if (a.loading) return <Loading />;
  if (!a.user) return <Navigate to="/login" replace />;
  if ((admin && !a.isAdmin) || (manager && !a.isManager))
    return <Navigate to="/" replace />;
  return children || <Outlet />;
}
function Shell() {
  const a = useAuth(),
    [open, setOpen] = useState(false),
    [error, setError] = useState(null),
    location = useLocation();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api("/health"),
    refetchInterval: 30000,
  });
  const links = [
    ["/", "Overview", LayoutDashboard],
    ["/tickets", "Ticket workbench", Ticket],
    ["/kb", "Knowledge base", BookOpen],
    ...(a.isManager
      ? [
          ["/accounts", "Accounts", Building2],
          ["/analytics", "AI analytics", ChartNoAxesCombined],
        ]
      : []),
    ...(a.isAdmin ? [["/admin", "Administration", Settings]] : []),
  ];
  return (
    <div className="app-shell">
      <aside className={"sidebar " + (open ? "open" : "")}>
        <Button
          className="mobile-close"
          variant="ghost"
          size="icon"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        >
          <X size={18} />
        </Button>
        <div className="wordmark">
          zycus<span className="text-blue-500">.</span>
        </div>
        <div className="product-name">SUPPORT INTELLIGENCE</div>
        <div className="nav-group">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {links.map(([to, label, Icon]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className="nav-link"
              onClick={() => setOpen(false)}
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck size={20} className="mb-2 text-blue-500" />
          <strong>Evidence before action</strong>
          <br />
          Internal decision support.
          <br />
          Source tickets remain unchanged.
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="flex items-center gap-3">
            <Button
              className="mobile-toggle"
              variant="ghost"
              size="icon"
              aria-label="Open navigation"
              onClick={() => setOpen(true)}
            >
              <Menu size={20} />
            </Button>
            <div className="topbar-breadcrumb">
              Workspace <span className="mx-3">/</span>
              <strong>
                {links.find(
                  ([p]) => p !== "/" && location.pathname.startsWith(p),
                )?.[1] || "Overview"}
              </strong>
            </div>
          </div>
          <div className="flex items-center gap-5">
            <span className="text-[10px] muted flex items-center gap-2">
              <span
                className={
                  "size-1.5 rounded-full " +
                  (health.data ? "bg-emerald-500" : "bg-slate-300")
                }
              />
              {health.data ? "API online" : "API unavailable"}
            </span>
            <div className="avatar">
              {a.user.name
                .split(" ")
                .map((n) => n[0])
                .slice(0, 2)
                .join("")}
            </div>
            <div className="user-name">
              <div className="text-xs font-semibold">{a.user.name}</div>
              <div className="text-[10px] muted capitalize">{a.user.role}</div>
            </div>
            <Button
              aria-label="Sign out"
              variant="ghost"
              size="icon"
              onClick={() => a.logout().catch(setError)}
            >
              <LogOut size={16} />
            </Button>
          </div>
        </header>
        <main className="content">
          {error && <ErrorState error={error} />}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
function Login() {
  const a = useAuth(),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [pending, setPending] = useState(false),
    [error, setError] = useState(null);
  if (a.loading) return <Loading />;
  if (a.user) return <Navigate to="/" replace />;
  return (
    <div className="login-layout">
      <section className="login-brand">
        <div className="text-4xl font-extrabold tracking-tighter">zycus.</div>
        <div>
          <div className="eyebrow text-blue-200 mb-5">
            SUPPORT INTELLIGENCE PLATFORM
          </div>
          <h2>
            Understand the issue.
            <br />
            Know the next move.
          </h2>
          <p className="mt-6">
            Investigate existing tickets with AI, connect account signals with
            trusted knowledge, and give your team an evidence-backed starting
            point.
          </p>
          <div className="mt-10 text-xs text-blue-200">
            Explainable decisions ? Human oversight
          </div>
        </div>
        <div className="text-xs text-blue-200/60">
          Internal support workspace ? Powered by Groq
        </div>
      </section>
      <section className="login-form">
        <div className="eyebrow">WELCOME BACK</div>
        <h1>Sign in to your workspace</h1>
        <p className="text-sm muted">
          Use your support team credentials to continue.
        </p>
        {error && <ErrorState error={error} />}
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setPending(true);
            setError(null);
            try {
              await a.login(email, password);
            } catch (e) {
              setError(e);
            } finally {
              setPending(false);
            }
          }}
        >
          <label>
            Email address
            <input
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <Button type="submit" disabled={pending}>
            {pending ? "Signing in?" : "Sign in"}
            <ArrowRight size={15} />
          </Button>
        </form>
        <p className="text-xs muted mt-7">
          Access is controlled by your administrator. Recommendations remain
          subject to human review.
        </p>
      </section>
    </div>
  );
}
export default function App() {
  return (
    <Suspense fallback={<Loading/>}><Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Guard>
            <Shell />
          </Guard>
        }
      >
        <Route index element={<Overview />} />
        <Route path="tickets" element={<Tickets />} />
        <Route path="tickets/:tid" element={<TicketDetail />} />
        <Route path="investigations/:rid" element={<Investigation />} />
        <Route path="kb" element={<Knowledge />} />
        <Route path="kb/:kid" element={<Knowledge />} />
        <Route
          path="accounts"
          element={
            <Guard manager>
              <Accounts />
            </Guard>
          }
        />
        <Route path="accounts/:aid" element={<Accounts />} />
        <Route
          path="analytics"
          element={
            <Guard manager>
              <Analytics />
            </Guard>
          }
        />
        <Route
          path="admin"
          element={
            <Guard admin>
              <Admin />
            </Guard>
          }
        />
        <Route path="*" element={<h1>Page not found</h1>} />
      </Route>
    </Routes></Suspense>
  );
}
