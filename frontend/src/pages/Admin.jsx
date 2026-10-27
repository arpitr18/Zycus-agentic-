import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, UserCog, X, Shield, Activity, Settings2 } from "lucide-react";
import { api, send, formatDate } from "../api";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "../components/ui/card";
import { Button } from "../components/ui/button";
import {
  PageHeader,
  Loading,
  ErrorState,
  Status,
  KeyValue,
  Json,
  Pagination,
} from "../components/shared";
function UserEditor({ user, accounts, onClose }) {
  const cache = useQueryClient(),
    [form, setForm] = useState(
      user
        ? { ...user, password: "" }
        : {
            email: "",
            name: "",
            role: "support",
            password: "",
            active: true,
            account_ids: [],
          },
    );
  const mutation = useMutation({
    mutationFn: () =>
      send(
        user ? "/users/" + user.id : "/users",
        { ...form, password: form.password || null },
        user ? "PUT" : "POST",
      ),
    onSuccess: () => {
      cache.invalidateQueries();
      onClose();
    },
  });
  function field(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }
  return (
    <div className="modal-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-editor-title"
        className="modal"
      >
        <div className="flex justify-between items-center mb-5">
          <h2 id="user-editor-title" className="font-semibold">
            {user ? "Edit user" : "Add team member"}
          </h2>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close user editor"
            onClick={onClose}
          >
            <X size={17} />
          </Button>
        </div>
        {mutation.error && <ErrorState error={mutation.error} />}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
          className="space-y-4"
        >
          <div className="field-grid">
            <label>
              Full name
              <input
                required
                maxLength={100}
                value={form.name}
                onChange={(e) => field("name", e.target.value)}
              />
            </label>
            <label>
              Email
              <input
                type="email"
                required
                value={form.email}
                onChange={(e) => field("email", e.target.value)}
              />
            </label>
            <label>
              Role
              <select
                value={form.role}
                onChange={(e) => field("role", e.target.value)}
              >
                <option value="support">Support engineer</option>
                <option value="manager">TAM / support manager</option>
                <option value="admin">Administrator</option>
              </select>
            </label>
            <label>
              {user ? "New password (optional)" : "Initial password"}
              <input
                type="password"
                autoComplete="new-password"
                minLength={10}
                required={!user}
                value={form.password}
                onChange={(e) => field("password", e.target.value)}
                placeholder="At least 10 characters"
              />
            </label>
          </div>
          <label>
            Assigned accounts
            <select
              multiple
              size={7}
              value={form.account_ids}
              onChange={(e) =>
                field(
                  "account_ids",
                  Array.from(e.target.selectedOptions, (o) => o.value),
                )
              }
            >
              {accounts.map((a) => (
                <option value={a.account_id} key={a.account_id}>
                  {a.company_name} ? {a.account_id}
                </option>
              ))}
            </select>
            <span className="muted text-[10px]">
              Use Ctrl/Cmd to select multiple. Support access is restricted to
              these accounts; manager/admin roles have full account scope.
            </span>
          </label>
          <label className="!flex items-center gap-2">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(e) => field("active", e.target.checked)}
            />
            Active user
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Saving?" : "Save user"}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
function Pricing({ settings }) {
  const cache = useQueryClient(),
    [text, setText] = useState(JSON.stringify(settings.pricing, null, 2)),
    [parseError, setParseError] = useState(null);
  const mutation = useMutation({
    mutationFn: (value) => send("/settings/pricing", value, "PUT"),
    onSuccess: () => cache.invalidateQueries(),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Verified model pricing</CardTitle>
        <p className="text-xs muted mt-1">
          USD per million tokens. Rates are never guessed or automatically
          backfilled.
        </p>
      </CardHeader>
      <CardContent>
        {mutation.isSuccess && (
          <div className="success-message">
            Pricing saved for future investigations.
          </div>
        )}
        {(parseError || mutation.error) && (
          <ErrorState error={parseError || mutation.error} />
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            try {
              setParseError(null);
              mutation.mutate(JSON.parse(text));
            } catch (error) {
              setParseError(error);
            }
          }}
        >
          <label>
            Pricing configuration
            <textarea
              className="font-mono !text-xs !min-h-[220px]"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <p className="text-xs muted my-4">
            Each model entry needs numeric <code>input_per_million</code>,{" "}
            <code>output_per_million</code>, and a <code>source</code> URL or
            reference. An empty object leaves costs unavailable.
          </p>
          <Button type="submit" disabled={mutation.isPending}>
            Save pricing
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
export default function Admin() {
  const [tab, setTab] = useState("users"),
    [editing, setEditing] = useState(undefined),
    [page, setPage] = useState(1);
  const users = useQuery({ queryKey: ["users"], queryFn: () => api("/users") }),
    accounts = useQuery({
      queryKey: ["accounts"],
      queryFn: () => api("/accounts"),
    }),
    settings = useQuery({
      queryKey: ["settings"],
      queryFn: () => api("/settings"),
    }),
    audit = useQuery({
      queryKey: ["audit", page],
      queryFn: () => api("/audit?page=" + page),
      enabled: tab === "audit",
    });
  if (users.isPending || settings.isPending || accounts.isPending)
    return <Loading />;
  const error = users.error || settings.error || accounts.error;
  if (error) return <ErrorState error={error} />;
  return (
    <>
      <PageHeader
        title="Administration"
        description="Manage access, account assignments, audit history, and operational configuration."
        action={
          tab === "users" && (
            <Button onClick={() => setEditing(null)}>
              <Plus size={15} />
              Add team member
            </Button>
          )
        }
      />
      <div className="tab-strip">
        {[
          ["users", "Users & roles"],
          ["audit", "Audit log"],
          ["settings", "System & pricing"],
        ].map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "users" && (
        <Card>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Account assignments</th>
                  <th>Status</th>
                  <th>Manage</th>
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong className="table-title">{user.name}</strong>
                      <span className="ticket-id">{user.email}</span>
                    </td>
                    <td className="capitalize">{user.role}</td>
                    <td>
                      {user.role === "support"
                        ? user.account_ids.length + " assigned accounts"
                        : "All accounts"}
                    </td>
                    <td>
                      <Status value={user.active ? "current" : "disabled"} />
                    </td>
                    <td>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setEditing(user)}
                      >
                        <UserCog size={13} />
                        Edit
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {tab === "audit" &&
        (audit.isPending ? (
          <Loading />
        ) : audit.error ? (
          <ErrorState error={audit.error} />
        ) : (
          <Card>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.data.items.map((event) => (
                    <tr key={event.id}>
                      <td className="whitespace-nowrap">
                        {formatDate(event.created_at)}
                      </td>
                      <td>
                        {event.actor_id
                          ? "User #" + event.actor_id
                          : "Unauthenticated"}
                      </td>
                      <td>{event.action}</td>
                      <td className="max-w-[220px] break-all">
                        {event.target}
                      </td>
                      <td>
                        <details>
                          <summary className="link cursor-pointer">
                            Inspect
                          </summary>
                          <Json value={event.detail} />
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={page}
              pageSize={30}
              total={audit.data.total}
              onPage={setPage}
            />
          </Card>
        ))}
      {tab === "settings" && (
        <div className="two-equal">
          <Card>
            <CardHeader>
              <CardTitle>System health & configuration</CardTitle>
            </CardHeader>
            <CardContent>
              <KeyValue label="Configured model">
                {settings.data.model}
              </KeyValue>
              <KeyValue label="Groq credential">
                {settings.data.groq_configured
                  ? "Configured (hidden)"
                  : "Not configured"}
              </KeyValue>
              <KeyValue label="Secure session cookies">
                {settings.data.secure_cookies
                  ? "Enabled"
                  : "Development HTTP mode"}
              </KeyValue>
              <KeyValue label="Demo users">
                {settings.data.demo_accounts_enabled
                  ? "Development-only seeding enabled"
                  : "Disabled"}
              </KeyValue>
              <KeyValue label="Worker">{settings.data.worker}</KeyValue>
              <KeyValue label="Database">{settings.data.database}</KeyValue>
              <KeyValue label="Source tickets">
                {settings.data.ticket_count}
              </KeyValue>
              <KeyValue label="KB articles">{settings.data.kb_count}</KeyValue>
              <KeyValue label="Dataset clock">
                {settings.data.reference_date}
              </KeyValue>
              <p className="notice mt-5">
                Agent credentials and model settings are configured on the
                server. No external ticketing integration is simulated.
              </p>
            </CardContent>
          </Card>
          <Pricing settings={settings.data} />
        </div>
      )}
      {editing !== undefined && (
        <UserEditor
          user={editing}
          accounts={accounts.data.items}
          onClose={() => setEditing(undefined)}
        />
      )}
    </>
  );
}
