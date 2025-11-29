import { useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { toast } from 'react-hot-toast';
import { creditsApi, authApi } from '../../../services/api';
import { Section } from '../shared';
import type { ManagedUser, CreditTransaction } from '../../../types';

export default function CreditsTab() {
  return (
    <div className="space-y-6">
      <CreditAdjustmentSection />
      <CreditLedgerSection />
      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </div>
  );
}

// --- Credit Adjustment Section ---
function CreditAdjustmentSection() {
  const [adjustForm, setAdjustForm] = useState<{ userId: string; amount: string; note: string }>({
    userId: '',
    amount: '',
    note: '',
  });

  const { data: managedUsers } = useQuery<ManagedUser[]>({
    queryKey: ['auth-users'],
    queryFn: async () => {
      const response = await authApi.listUsers();
      return response.users;
    },
  });

  const creditsAdjustMutation = useMutation({
    mutationFn: () =>
      creditsApi.manualAdjust(Number(adjustForm.userId), adjustForm.amount, adjustForm.note || undefined),
    onSuccess: () => {
      toast.success('Credits updated.');
      setAdjustForm({ userId: '', amount: '', note: '' });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to adjust credits.'));
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    creditsAdjustMutation.mutate();
  };

  return (
    <Section title="Manual Credit Adjustment">
      <form className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end" onSubmit={handleSubmit}>
        <label className="text-sm text-gray-700">
          User
          <select
            className="mt-1 block w-full border border-gray-300 rounded-md p-2"
            value={adjustForm.userId}
            onChange={(e) => setAdjustForm((prev) => ({ ...prev, userId: e.target.value }))}
            required
          >
            <option value="">Select user</option>
            {managedUsers?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username} ({u.role})
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-gray-700">
          Amount (positive or negative)
          <input
            type="number"
            step="0.01"
            className="mt-1 block w-full border border-gray-300 rounded-md p-2"
            value={adjustForm.amount}
            onChange={(e) => setAdjustForm((prev) => ({ ...prev, amount: e.target.value }))}
            required
          />
        </label>
        <label className="text-sm text-gray-700 md:col-span-3">
          Note (optional)
          <input
            type="text"
            className="mt-1 block w-full border border-gray-300 rounded-md p-2"
            value={adjustForm.note}
            onChange={(e) => setAdjustForm((prev) => ({ ...prev, note: e.target.value }))}
            placeholder="e.g., manual top-up or correction"
          />
        </label>
        <div className="md:col-span-3">
          <button
            type="submit"
            disabled={creditsAdjustMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {creditsAdjustMutation.isPending ? 'Updating…' : 'Apply adjustment'}
          </button>
        </div>
      </form>
    </Section>
  );
}

// --- Credit Ledger Section ---
function CreditLedgerSection() {
  const [limit, setLimit] = useState(20);

  const { data: ledgerData, isLoading, refetch } = useQuery({
    queryKey: ['credit-ledger', limit],
    queryFn: () => creditsApi.getLedger(limit, true), // all=true to get all users' transactions
  });

  const transactions = ledgerData?.transactions ?? [];

  const formatAmount = (amount: string) => {
    const num = parseFloat(amount);
    if (num >= 0) {
      return <span className="text-green-600">+{amount}</span>;
    }
    return <span className="text-red-600">{amount}</span>;
  };

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString();
  };

  const getTypeLabel = (type: string) => {
    switch (type) {
      case 'manual_adjustment':
        return 'Manual Adjustment';
      case 'processing_charge':
        return 'Processing Charge';
      case 'initial_balance':
        return 'Initial Balance';
      default:
        return type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    }
  };

  return (
    <Section title="Credit Transaction History">
      <div className="space-y-4">
        {/* Controls */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">Show:</label>
            <select
              className="border border-gray-300 rounded-md px-2 py-1 text-sm"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <span className="text-sm text-gray-600">transactions</span>
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            className="text-sm text-indigo-600 hover:underline"
          >
            Refresh
          </button>
        </div>

        {/* Table */}
        {isLoading ? (
          <div className="text-sm text-gray-600">Loading transactions...</div>
        ) : transactions.length === 0 ? (
          <div className="text-sm text-gray-600">No transactions found.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Date
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    User
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Amount
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Note
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {transactions.map((tx: CreditTransaction) => (
                  <tr key={tx.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">
                      {formatDate(tx.created_at)}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-900 whitespace-nowrap">
                      {tx.username || `User #${tx.user_id}`}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-900">
                      {getTypeLabel(tx.type)}
                    </td>
                    <td className="px-4 py-2 text-sm text-right font-mono">
                      {formatAmount(tx.amount)}
                    </td>
                    <td className="px-4 py-2 text-sm text-gray-600 max-w-xs truncate">
                      {tx.note || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
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
