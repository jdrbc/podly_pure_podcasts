import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'react-hot-toast';
import { authApi } from '../../../services/api';
import { useAuth } from '../../../contexts/AuthContext';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, SaveButton } from '../shared';
import type { ManagedUser } from '../../../types';

export default function UserManagementTab() {
  const { changePassword, refreshUser, user, logout } = useAuth();
  const { pending, setField, handleSave, isSaving } = useConfigContext();

  const {
    data: managedUsers,
    isLoading: usersLoading,
    refetch: refetchUsers,
  } = useQuery<ManagedUser[]>({
    queryKey: ['auth-users'],
    queryFn: async () => {
      const response = await authApi.listUsers();
      return response.users;
    },
  });

  const totalUsers = useMemo(() => managedUsers?.length ?? 0, [managedUsers]);
  const limitValue = pending?.app?.user_limit_total ?? null;

  return (
    <div className="space-y-6">
      <AccountSecuritySection
        changePassword={changePassword}
        refreshUser={refreshUser}
      />
      {pending && (
        <UserLimitSection
          currentUsers={totalUsers}
          userLimit={limitValue}
          onChangeLimit={(value) =>
            setField(
              ['app', 'user_limit_total'],
              value === '' ? null : Number(value)
            )
          }
          onSave={handleSave}
          isSaving={isSaving}
          isLoadingUsers={usersLoading}
        />
      )}
      <UserManagementSection
        currentUser={user}
        refreshUser={refreshUser}
        logout={logout}
        managedUsers={managedUsers}
        usersLoading={usersLoading}
        refetchUsers={refetchUsers}
      />
    </div>
  );
}

// --- Account Security Section ---
interface AccountSecurityProps {
  changePassword: (current: string, next: string) => Promise<void>;
  refreshUser: () => Promise<void>;
}

function AccountSecuritySection({ changePassword, refreshUser }: AccountSecurityProps) {
  const [passwordForm, setPasswordForm] = useState({ current: '', next: '', confirm: '' });
  const [passwordSubmitting, setPasswordSubmitting] = useState(false);

  const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (passwordForm.next !== passwordForm.confirm) {
      toast.error('New passwords do not match.');
      return;
    }

    setPasswordSubmitting(true);
    try {
      await changePassword(passwordForm.current, passwordForm.next);
      toast.success('Password updated. Update PODLY_ADMIN_PASSWORD to match.');
      setPasswordForm({ current: '', next: '', confirm: '' });
      await refreshUser();
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update password.'));
    } finally {
      setPasswordSubmitting(false);
    }
  };

  return (
    <Section title="Account Security">
      <form className="grid gap-3 max-w-md" onSubmit={handlePasswordSubmit}>
        <Field label="Current password">
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={passwordForm.current}
            onChange={(event) =>
              setPasswordForm((prev) => ({ ...prev, current: event.target.value }))
            }
            required
          />
        </Field>
        <Field label="New password">
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={passwordForm.next}
            onChange={(event) =>
              setPasswordForm((prev) => ({ ...prev, next: event.target.value }))
            }
            required
          />
        </Field>
        <Field label="Confirm new password">
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={passwordForm.confirm}
            onChange={(event) =>
              setPasswordForm((prev) => ({ ...prev, confirm: event.target.value }))
            }
            required
          />
        </Field>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            className="px-4 py-2 rounded bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-60"
            disabled={passwordSubmitting}
          >
            {passwordSubmitting ? 'Updating…' : 'Update password'}
          </button>
          <p className="text-xs text-gray-500">
            After updating, rotate <code className="font-mono">PODLY_ADMIN_PASSWORD</code> to match.
          </p>
        </div>
      </form>
      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </Section>
  );
}

// --- User Limit Section ---
interface UserLimitSectionProps {
  currentUsers: number;
  userLimit: number | null;
  onChangeLimit: (value: string) => void;
  onSave: () => void;
  isSaving: boolean;
  isLoadingUsers: boolean;
}

function UserLimitSection({ currentUsers, userLimit, onChangeLimit, onSave, isSaving, isLoadingUsers }: UserLimitSectionProps) {
  return (
    <Section title="User Limits">
      <div className="grid gap-3 md:grid-cols-2 md:items-end">
        <Field label="Total users allowed">
          <input
            className="input"
            type="number"
            min={0}
            value={userLimit ?? ''}
            onChange={(event) => onChangeLimit(event.target.value)}
            placeholder="Unlimited"
          />
          <p className="text-xs text-gray-500 mt-1">
            Leave blank for unlimited; set to 0 to block new user creation. Applies only when authentication is enabled.
          </p>
        </Field>
        <div className="text-sm text-gray-700 space-y-1">
          <div className="font-semibold">Current users</div>
          <div>{isLoadingUsers ? 'Loading…' : currentUsers}</div>
          {userLimit !== null && userLimit > 0 && currentUsers >= userLimit ? (
            <div className="text-xs text-red-600">
              Limit reached. New users are blocked until the total drops below {userLimit}.
            </div>
          ) : (
            <div className="text-xs text-gray-500">
              New user creation is blocked once the limit is reached.
            </div>
          )}
        </div>
      </div>
      <div className="mt-3">
        <SaveButton onSave={onSave} isPending={isSaving} />
      </div>
      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </Section>
  );
}

// --- User Management Section ---
interface UserManagementProps {
  currentUser: { id: number; username: string; role: string } | null;
  refreshUser: () => Promise<void>;
  logout: () => void;
  managedUsers: ManagedUser[] | undefined;
  usersLoading: boolean;
  refetchUsers: () => Promise<unknown>;
}

function UserManagementSection({ currentUser, refreshUser, logout, managedUsers, usersLoading, refetchUsers }: UserManagementProps) {
  const [newUser, setNewUser] = useState({ username: '', password: '', confirm: '', role: 'user' });
  const [activeResetUser, setActiveResetUser] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [resetConfirm, setResetConfirm] = useState('');

  const sortedUsers = useMemo(() => {
    if (!managedUsers) {
      return [];
    }
    return [...managedUsers].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [managedUsers]);
  const adminCount = useMemo(
    () => sortedUsers.filter((u) => u.role === 'admin').length,
    [sortedUsers]
  );

  const handleCreateUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const username = newUser.username.trim();
    if (!username) {
      toast.error('Username is required.');
      return;
    }
    if (newUser.password !== newUser.confirm) {
      toast.error('Passwords do not match.');
      return;
    }

    try {
      await authApi.createUser({
        username,
        password: newUser.password,
        role: newUser.role,
      });
      toast.success(`User '${username}' created.`);
      setNewUser({ username: '', password: '', confirm: '', role: 'user' });
      await refetchUsers();
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to create user.'));
    }
  };

  const handleRoleChange = async (username: string, role: string) => {
    try {
      await authApi.updateUser(username, { role });
      toast.success(`Updated role for ${username}.`);
      await refetchUsers();
      if (currentUser && currentUser.username === username) {
        await refreshUser();
      }
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update role.'));
    }
  };

  const handleAllowanceChange = async (username: string, allowance: string) => {
    const val = allowance === '' ? null : parseInt(allowance, 10);
    if (val !== null && isNaN(val)) return;

    try {
      await authApi.updateUser(username, { manual_feed_allowance: val });
      toast.success(`Updated allowance for ${username}.`);
      await refetchUsers();
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update allowance.'));
    }
  };

  const handleResetPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeResetUser) {
      return;
    }
    if (resetPassword !== resetConfirm) {
      toast.error('Passwords do not match.');
      return;
    }

    try {
      await authApi.updateUser(activeResetUser, { password: resetPassword });
      toast.success(`Password updated for ${activeResetUser}.`);
      setActiveResetUser(null);
      setResetPassword('');
      setResetConfirm('');
      await refetchUsers();
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update password.'));
    }
  };

  const handleDeleteUser = async (username: string) => {
    const confirmed = window.confirm(`Delete user '${username}'? This action cannot be undone.`);
    if (!confirmed) {
      return;
    }
    try {
      await authApi.deleteUser(username);
      toast.success(`Deleted user '${username}'.`);
      await refetchUsers();
      if (currentUser && currentUser.username === username) {
        logout();
      }
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to delete user.'));
    }
  };

  return (
    <Section title="User Management">
      <div className="space-y-4">
        {/* Create User Form */}
        <form className="grid gap-3 md:grid-cols-2" onSubmit={handleCreateUser}>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              className="input"
              type="text"
              value={newUser.username}
              onChange={(event) => setNewUser((prev) => ({ ...prev, username: event.target.value }))}
              placeholder="new_user"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              className="input"
              type="password"
              value={newUser.password}
              onChange={(event) => setNewUser((prev) => ({ ...prev, password: event.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Confirm password</label>
            <input
              className="input"
              type="password"
              value={newUser.confirm}
              onChange={(event) => setNewUser((prev) => ({ ...prev, confirm: event.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select
              className="input"
              value={newUser.role}
              onChange={(event) => setNewUser((prev) => ({ ...prev, role: event.target.value }))}
            >
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div className="md:col-span-2 flex items-center justify-start">
            <button
              type="submit"
              className="px-4 py-2 rounded bg-green-600 text-white text-sm font-medium hover:bg-green-700"
            >
              Add user
            </button>
          </div>
        </form>

        {/* User List */}
        <div className="space-y-3">
          {usersLoading && <div className="text-sm text-gray-600">Loading users…</div>}
          {!usersLoading && (!managedUsers || managedUsers.length === 0) && (
            <div className="text-sm text-gray-600">No additional users configured.</div>
          )}
          {!usersLoading && managedUsers && managedUsers.length > 0 && (
            <div className="space-y-3">
              {sortedUsers.map((managed) => {
                const disableDemotion = managed.role === 'admin' && adminCount <= 1;
                const disableDelete = disableDemotion;
                const isActive = activeResetUser === managed.username;
                const allowance = managed.feed_allowance ?? 0;
                const subscriptionStatus = managed.feed_subscription_status ?? 'inactive';

                return (
                  <div
                    key={managed.id}
                    className="border border-gray-200 rounded-lg p-3 space-y-3 bg-white"
                  >
                    <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                      <div>
                        <div className="text-sm font-semibold text-gray-900">{managed.username}</div>
                        <div className="text-xs text-gray-500">
                          Added {new Date(managed.created_at).toLocaleString()} • Role {managed.role} • Feeds {allowance} • Status {subscriptionStatus}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="flex items-center gap-1" title="Override feed allowance">
                          <span className="text-xs text-gray-500">Feed Allowance Override:</span>
                          <input
                            className="input text-sm w-20 py-1"
                            type="number"
                            min="0"
                            placeholder="None"
                            defaultValue={managed.manual_feed_allowance ?? ''}
                            onBlur={(e) => {
                              const val = e.target.value;
                              const current = managed.manual_feed_allowance?.toString() ?? '';
                              if (val !== current) {
                                void handleAllowanceChange(managed.username, val);
                              }
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.currentTarget.blur();
                              }
                            }}
                          />
                        </div>
                        <select
                          className="input text-sm"
                          value={managed.role}
                          onChange={(event) => {
                            const nextRole = event.target.value;
                            if (nextRole !== managed.role) {
                              void handleRoleChange(managed.username, nextRole);
                            }
                          }}
                          disabled={disableDemotion && managed.role === 'admin'}
                        >
                          <option value="user">user</option>
                          <option value="admin">admin</option>
                        </select>
                        <button
                          type="button"
                          className="px-3 py-1 border border-gray-300 rounded-md text-sm hover:bg-gray-50"
                          onClick={() => {
                            if (isActive) {
                              setActiveResetUser(null);
                              setResetPassword('');
                              setResetConfirm('');
                            } else {
                              setActiveResetUser(managed.username);
                              setResetPassword('');
                              setResetConfirm('');
                            }
                          }}
                        >
                          {isActive ? 'Cancel' : 'Set password'}
                        </button>
                        <button
                          type="button"
                          className="px-3 py-1 border border-red-300 text-red-600 rounded-md text-sm hover:bg-red-50 disabled:opacity-50"
                          onClick={() => void handleDeleteUser(managed.username)}
                          disabled={disableDelete}
                        >
                          Delete
                        </button>
                      </div>
                    </div>

                    {isActive && (
                      <form className="grid gap-2 md:grid-cols-3" onSubmit={handleResetPassword}>
                        <div className="md:col-span-1">
                          <label className="block text-xs font-medium text-gray-600 mb-1">
                            New password
                          </label>
                          <input
                            className="input"
                            type="password"
                            value={resetPassword}
                            onChange={(event) => setResetPassword(event.target.value)}
                            required
                          />
                        </div>
                        <div className="md:col-span-1">
                          <label className="block text-xs font-medium text-gray-600 mb-1">
                            Confirm password
                          </label>
                          <input
                            className="input"
                            type="password"
                            value={resetConfirm}
                            onChange={(event) => setResetConfirm(event.target.value)}
                            required
                          />
                        </div>
                        <div className="md:col-span-1 flex items-end gap-2">
                          <button
                            type="submit"
                            className="px-4 py-2 rounded bg-indigo-600 text-white text-sm hover:bg-indigo-700"
                          >
                            Update
                          </button>
                          <p className="text-xs text-gray-500">Share new credentials securely.</p>
                        </div>
                      </form>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </Section>
  );
}

// Helper function
function getErrorMessage(error: unknown, fallback = 'Request failed.') {
  if (error && typeof error === 'object') {
    const err = error as {
      response?: { data?: { error?: string; message?: string } };
      message?: string;
    };
    return err.response?.data?.error || err.response?.data?.message || err.message || fallback;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}
