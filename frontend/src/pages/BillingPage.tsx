import { useEffect, useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { billingApi } from '../services/api';
import { toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';

export default function BillingPage() {
  const { user } = useAuth();
  if (user?.role === 'admin') {
    return <Navigate to="/" replace />;
  }
  const { data, refetch, isLoading } = useQuery({
    queryKey: ['billing', 'summary'],
    queryFn: billingApi.getSummary,
  });
  const [quantity, setQuantity] = useState<number>(data?.feed_allowance ?? 1);

  useEffect(() => {
    if (data) {
      setQuantity(data.feed_allowance);
    }
  }, [data]);

  const updateQuantity = useMutation({
    mutationFn: (qty: number) =>
      billingApi.setQuantity(qty, {
        subscriptionId: data?.stripe_subscription_id ?? null,
      }),
    onSuccess: (res) => {
      if (res.checkout_url) {
        window.location.href = res.checkout_url;
        return;
      }
      toast.success('Plan updated');
      setQuantity(res.feed_allowance);
      refetch();
    },
    onError: (err) => {
      console.error('Failed to update plan', err);
      toast.error('Could not update plan');
    },
  });

  const portalSession = useMutation({
    mutationFn: () => billingApi.createPortalSession(),
    onSuccess: (res) => {
      if (res.url) {
        window.location.href = res.url;
      }
    },
    onError: (err) => {
      console.error('Failed to open billing portal', err);
      toast.error('Unable to open billing portal');
    },
  });

  if (isLoading || !data) {
    return (
      <div className="p-6">
        <div className="text-sm text-gray-600">Loading billing…</div>
      </div>
    );
  }

  const monthlyTotal = (quantity || 0) * 2;
  const atCurrentQuantity = quantity === data.feed_allowance;
  const planLimitInfo = `${data.feeds_in_use}/${data.feed_allowance} feeds active`;

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Billing</h1>
        <p className="text-sm text-gray-600 mt-1">
          $1 per feed per month. Use checkout to start a subscription or the portal to manage billing.
        </p>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-5 space-y-4">
        <div className="flex flex-wrap gap-3 items-center justify-between">
          <div>
            <div className="text-sm text-gray-600">Current plan</div>
            <div className="text-lg font-semibold text-gray-900">
              {planLimitInfo}
            </div>
            <div className="text-xs text-gray-500">
              Subscription status: {data.subscription_status || 'inactive'}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-gray-600">Estimated monthly</div>
            <div className="text-2xl font-bold text-gray-900">${monthlyTotal}</div>
            <div className="text-xs text-gray-500">{quantity} feeds × 1</div>
          </div>
        </div>

        <div className="space-y-3">
          <div className="text-sm text-gray-700 font-medium">Feeds in plan</div>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setQuantity((q) => Math.max(0, q - 1))}
                className="px-3 py-2 rounded-md border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40"
                disabled={quantity <= 0 || updateQuantity.isPending}
              >
                −
              </button>
              <input
                type="number"
                min={0}
                value={quantity}
                onChange={(e) => setQuantity(Math.max(0, Number(e.target.value)))}
                className="w-24 text-center border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <button
                type="button"
                onClick={() => setQuantity((q) => q + 1)}
                className="px-3 py-2 rounded-md border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40"
                disabled={updateQuantity.isPending}
              >
                +
              </button>
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-600">
              <span>Quick set:</span>
              {[1, 3, 5, 10].map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setQuantity(preset)}
                  className={`px-2 py-1 rounded-md border text-xs transition-colors ${
                    quantity === preset
                      ? 'border-blue-200 bg-blue-50 text-blue-700'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                  disabled={updateQuantity.isPending}
                >
                  {preset}
                </button>
              ))}
            </div>
            <div className="flex-1 text-right text-xs text-gray-500">
              {planLimitInfo}
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <button
              onClick={() => updateQuantity.mutate(quantity)}
              disabled={updateQuantity.isPending || atCurrentQuantity}
              className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {updateQuantity.isPending ? 'Saving…' : atCurrentQuantity ? 'No changes' : 'Update plan'}
            </button>
            <div className="text-xs text-gray-500">
              Updating an existing subscription keeps your Stripe subscription ID and prorates quantity.
            </div>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-sm">
          <div className="text-gray-600">
            {data.subscription_status && data.subscription_status !== 'inactive'
              ? `Subscription status: ${data.subscription_status}`
              : 'No active subscription'}
          </div>
          <button
            onClick={() => portalSession.mutate()}
            disabled={portalSession.isPending || !data.stripe_customer_id}
            className="inline-flex items-center justify-center px-3 py-2 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-100 disabled:opacity-50 text-sm"
          >
            {portalSession.isPending ? 'Opening…' : 'Open billing portal'}
          </button>
        </div>
      </div>
    </div>
  );
}
