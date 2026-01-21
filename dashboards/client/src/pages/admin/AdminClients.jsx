import { useEffect, useMemo, useState } from "react";
import {
  RefreshCcw,
  Search,
  ShieldCheck,
  UserPlus,
  Mail,
  Ban,
  CheckCircle2,
  Send,
  Trash2,
} from "lucide-react";
import { useOutletContext } from "react-router-dom";
import {
  createUser,
  deleteUser,
  fetchUsers,
  sendInvite,
  updateUserSlots,
  updateUserStatus,
} from "../../services/api";

export default function AdminClients() {
  const { slots } = useOutletContext();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selectedEmail, setSelectedEmail] = useState("");
  const [selectionSlots, setSelectionSlots] = useState([]);
  const [savingSlots, setSavingSlots] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteSlots, setInviteSlots] = useState([]);
  const [inviteSend, setInviteSend] = useState(true);
  const [inviteState, setInviteState] = useState("");
  const [actionState, setActionState] = useState("");

  const loadUsers = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetchUsers();
      setUsers(res.users || []);
    } catch (err) {
      setError("Failed to load client roster.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const allSlots = useMemo(() => {
    return (slots || []).map((slot) => slot.slot_id).filter(Boolean);
  }, [slots]);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    const clients = users.filter((u) => u.role === "client");
    if (!term) return clients;
    return clients.filter((user) =>
      `${user.username} ${user.google_emails?.join(" ")}`.toLowerCase().includes(term)
    );
  }, [users, query]);

  const selectedUser = useMemo(() => {
    if (!filtered.length) return null;
    return (
      filtered.find((user) => user.username === selectedEmail) ||
      filtered[0] ||
      null
    );
  }, [filtered, selectedEmail]);

  useEffect(() => {
    if (selectedUser?.username) {
      setSelectedEmail(selectedUser.username);
      setSelectionSlots(selectedUser.allowed_slots || []);
    }
  }, [selectedUser?.username]);

  const toggleSelectionSlot = (slotId, setFn) => {
    setFn((prev) =>
      prev.includes(slotId) ? prev.filter((id) => id !== slotId) : [...prev, slotId]
    );
  };

  const handleSaveSlots = async () => {
    if (!selectedUser) return;
    setSavingSlots(true);
    setActionState("");
    try {
      await updateUserSlots(selectedUser.username, selectionSlots);
      await loadUsers();
      setActionState("Slot assignments saved.");
    } catch (err) {
      setActionState("Failed to update assignments.");
    } finally {
      setSavingSlots(false);
    }
  };

  const handleToggleStatus = async () => {
    if (!selectedUser) return;
    setActionState("");
    try {
      await updateUserStatus(selectedUser.username, !selectedUser.disabled);
      await loadUsers();
      setActionState(selectedUser.disabled ? "Client re-enabled." : "Client disabled.");
    } catch (err) {
      setActionState("Failed to update client status.");
    }
  };

  const handleDelete = async () => {
    if (!selectedUser) return;
    setActionState("");
    try {
      await deleteUser(selectedUser.username);
      await loadUsers();
      setSelectedEmail("");
      setActionState("Client removed.");
    } catch (err) {
      setActionState("Failed to delete client.");
    }
  };

  const handleResendInvite = async () => {
    if (!selectedUser) return;
    setActionState("");
    try {
      await sendInvite({ email: selectedUser.username });
      setActionState("Invite sent.");
    } catch (err) {
      setActionState("Failed to send invite.");
    }
  };

  const handleCreate = async () => {
    if (!inviteEmail) return;
    setInviteState("");
    try {
      await createUser({
        email: inviteEmail,
        role: "client",
        allowed_slots: inviteSlots,
        send_invite: inviteSend,
      });
      setInviteEmail("");
      setInviteSlots([]);
      setInviteState(inviteSend ? "Client invited." : "Client created.");
      await loadUsers();
    } catch (err) {
      setInviteState(err?.message || "Failed to invite client.");
    }
  };

  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Client control</div>
            <div className="engyne-card-title">Access & onboarding</div>
            <div className="engyne-card-helper">
              Invite clients, assign slots, and monitor onboarding status.
            </div>
          </div>
          <div className="engyne-inline-actions">
            <div className="engyne-search">
              <Search size={14} />
              <input
                className="engyne-search-input"
                placeholder="Search clients"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <button className="engyne-btn engyne-btn--ghost engyne-btn--small" onClick={loadUsers}>
              <RefreshCcw size={14} />
              Refresh
            </button>
          </div>
        </div>
        {loading && <div className="engyne-muted">Loading clients...</div>}
        {error && <div className="engyne-alert engyne-alert--danger">{error}</div>}
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-4 min-h-0">
        <section className="engyne-panel-soft engyne-card engyne-slot-list">
          {filtered.length === 0 ? (
            <div className="engyne-empty">No invited clients yet.</div>
          ) : (
            <div className="engyne-slot-stack">
              {filtered.map((user) => {
                const isActive = selectedUser?.username === user.username;
                return (
                  <button
                    key={user.username}
                    className={`engyne-slot-row ${isActive ? "is-active" : ""}`}
                    onClick={() => setSelectedEmail(user.username)}
                  >
                    <div>
                      <div className="engyne-slot-title">{user.username}</div>
                      <div className="engyne-slot-meta">
                        {user.onboarding_complete ? "Onboarded" : "Onboarding pending"} ·{" "}
                        {user.allowed_slots?.length || 0} slots
                      </div>
                    </div>
                    <div className="engyne-slot-actions">
                      <span className={`engyne-pill ${user.disabled ? "engyne-pill--danger" : "engyne-pill--good"}`}>
                        {user.disabled ? "disabled" : "active"}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section className="engyne-panel engyne-card">
          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">Invite client</div>
              <div className="engyne-card-title">Create new access</div>
              <div className="engyne-card-helper">
                Clients can log in only with their invited Google account.
              </div>
            </div>
            <UserPlus size={18} className="text-[var(--engyne-muted)]" />
          </div>

          <div className="engyne-form-fields">
            <label className="engyne-field">
              <span>Email address</span>
              <input
                className="engyne-input"
                type="email"
                placeholder="client@company.com"
                value={inviteEmail}
                onChange={(event) => setInviteEmail(event.target.value)}
              />
            </label>

            <div className="engyne-field">
              <span>Assign slots</span>
              <div className="engyne-checklist">
                {allSlots.map((slotId) => (
                  <label key={slotId} className="engyne-check">
                    <input
                      type="checkbox"
                      checked={inviteSlots.includes(slotId)}
                      onChange={() => toggleSelectionSlot(slotId, setInviteSlots)}
                    />
                    <span>{slotId}</span>
                  </label>
                ))}
              </div>
            </div>

            <label className="engyne-toggle">
              <span>Send invite email now</span>
              <span className={`engyne-toggle-pill ${inviteSend ? "is-on" : ""}`}>
                {inviteSend ? "On" : "Off"}
              </span>
              <input
                type="checkbox"
                checked={inviteSend}
                onChange={() => setInviteSend((prev) => !prev)}
              />
            </label>
          </div>

          <div className="engyne-inline-actions">
            <button className="engyne-btn engyne-btn--primary" onClick={handleCreate}>
              <Mail size={14} />
              Invite client
            </button>
            {inviteState && <span className="engyne-muted">{inviteState}</span>}
          </div>

          <div className="engyne-divider" />

          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">Client detail</div>
              <div className="engyne-card-title">
                {selectedUser ? selectedUser.username : "Select a client"}
              </div>
              <div className="engyne-card-helper">
                {selectedUser
                  ? `${selectedUser.allowed_slots?.length || 0} slots assigned`
                  : "Pick a client to manage access."}
              </div>
            </div>
            {selectedUser && (
              <div className="engyne-inline-actions">
                <button
                  className="engyne-btn engyne-btn--ghost engyne-btn--small"
                  onClick={handleResendInvite}
                >
                  <Send size={14} />
                  Resend invite
                </button>
                <button
                  className="engyne-btn engyne-btn--ghost engyne-btn--small"
                  onClick={handleToggleStatus}
                >
                  {selectedUser.disabled ? <CheckCircle2 size={14} /> : <Ban size={14} />}
                  {selectedUser.disabled ? "Enable" : "Disable"}
                </button>
                <button
                  className="engyne-btn engyne-btn--ghost engyne-btn--small"
                  onClick={handleDelete}
                >
                  <Trash2 size={14} />
                  Delete
                </button>
              </div>
            )}
          </div>

          {!selectedUser ? (
            <div className="engyne-empty">No client selected.</div>
          ) : (
            <>
              <div className="engyne-slot-detail-grid">
                <div className="engyne-detail-card">
                  <div className="engyne-detail-label">Status</div>
                  <div className="engyne-detail-value">
                    {selectedUser.disabled ? "Disabled" : "Active"}
                  </div>
                </div>
                <div className="engyne-detail-card">
                  <div className="engyne-detail-label">Onboarding</div>
                  <div className="engyne-detail-value">
                    {selectedUser.onboarding_complete ? "Complete" : "Pending"}
                  </div>
                </div>
                <div className="engyne-detail-card">
                  <div className="engyne-detail-label">Aliases</div>
                  <div className="engyne-detail-value">
                    {selectedUser.google_emails?.length ? selectedUser.google_emails.length : 0}
                  </div>
                </div>
              </div>

              <div className="engyne-field">
                <span>Assigned slots</span>
                <div className="engyne-checklist">
                  {allSlots.map((slotId) => (
                    <label key={slotId} className="engyne-check">
                      <input
                        type="checkbox"
                        checked={selectionSlots.includes(slotId)}
                        onChange={() => toggleSelectionSlot(slotId, setSelectionSlots)}
                      />
                      <span>{slotId}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="engyne-inline-actions">
                <button
                  className="engyne-btn engyne-btn--primary"
                  onClick={handleSaveSlots}
                  disabled={savingSlots}
                >
                  <ShieldCheck size={14} />
                  {savingSlots ? "Saving..." : "Save assignments"}
                </button>
                {actionState && <span className="engyne-muted">{actionState}</span>}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
