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
  
  // Amount in dollars
  const [amount, setAmount] = useState<number>(5);

  useEffect(() => {
    if (data?.current_amount) {
      setAmount(data.current_amount / 100);
    }
  }, [data]);

  const updateSubscription = useMutation({
    mutationFn: (amt: number) =>
      billingApi.updateSubscription(Math.round(amt * 100), {
        subscriptionId: data?.stripe_subscription_id ?? null,
      }),
    onSuccess: (res) => {
      if (res.checkout_url) {
        window.location.href = res.checkout_url;
        return;
      }
      toast.success('Plan updated');
      if (res.current_amount) {
          setAmount(res.current_amount / 100);
      }
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

  const isSubscribed = data.subscription_status === 'active' || data.subscription_status === 'trialing';
  const currentAmountDollars = data.current_amount ? data.current_amount / 100 : 0;
  const atCurrentAmount = amount === currentAmountDollars && isSubscribed;
  const planLimitInfo = `${data.feeds_in_use}/${data.feed_allowance} feeds active`;
  const minAmountCents = data.min_amount_cents ?? 100;
  const minAmountDollars = minAmountCents / 100;

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Billing</h1>
        <p className="text-sm text-gray-600 mt-1">
          Pay what you want for the Starter Bundle (10 feeds).
        </p>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-5 space-y-4">
        <div className="flex flex-wrap gap-3 items-center justify-between">
          <div>
            <div className="text-sm text-gray-600">Current plan</div>
            <div className="text-lg font-semibold text-gray-900">
              {isSubscribed ? 'Starter Bundle (10 Feeds)' : 'Free Tier'}
            </div>
            <div className="text-xs text-gray-500">
              {planLimitInfo}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-gray-600">Monthly payment</div>
            <div className="text-2xl font-bold text-gray-900">
                {isSubscribed ? `$${currentAmountDollars.toFixed(2)}` : '$0.00'}
            </div>
            <div className="text-xs text-gray-500">
              Subscription status: {data.subscription_status || 'inactive'}
            </div>
          </div>
        </div>

        <div className="space-y-3 pt-4 border-t border-gray-100">
          <div className="text-sm text-gray-700 font-medium">
            {isSubscribed ? 'Update your price' : 'Subscribe to Starter Bundle'}
          </div>
          <p className="text-sm text-gray-600">
            Get 10 feeds for a monthly price of your choice (min ${minAmountDollars.toFixed(2)}).
          </p>
          
          <div className="text-xs text-amber-800 bg-amber-50 p-3 rounded-md border border-amber-200">
            <strong>Note:</strong> We suggest paying ~$1 per feed you use. If revenue doesn't cover server costs, we may have to shut down the service.
          </div>
          
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="relative rounded-md shadow-sm w-32">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <span className="text-gray-500 sm:text-sm">$</span>
              </div>
              <input
                type="number"
                min={minAmountDollars}
                step={0.5}
                value={amount}
                onChange={(e) => setAmount(Math.max(0, Number(e.target.value)))}
                className="block w-full rounded-md border-gray-300 pl-7 pr-3 py-2 focus:border-blue-500 focus:ring-blue-500 sm:text-sm border"
                placeholder="5.00"
              />
            </div>
            
            <div className="flex items-center gap-2 text-xs text-gray-600">
              <span>Suggested:</span>
              {[3, 5, 10, 15].map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setAmount(preset)}
                  className={`px-2 py-1 rounded-md border text-xs transition-colors ${
                    amount === preset
                      ? 'border-blue-200 bg-blue-50 text-blue-700'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                  disabled={updateSubscription.isPending}
                >
                  ${preset}
                </button>
              ))}
            </div>
          </div>
          
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center pt-2">
            <button
              onClick={() => updateSubscription.mutate(amount)}
              disabled={updateSubscription.isPending || atCurrentAmount || amount < minAmountDollars}
              className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {updateSubscription.isPending 
                ? 'Processing…' 
                : isSubscribed 
                  ? (atCurrentAmount ? 'Current Price' : 'Update Price') 
                  : 'Subscribe'}
            </button>
            {amount < minAmountDollars && (
                <span className="text-xs text-red-500">Minimum amount is ${minAmountDollars.toFixed(2)}</span>
            )}
          </div>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-sm pt-4 border-t border-gray-100">
          <div className="text-gray-500 text-xs">
             Payments are securely processed by Stripe. You can cancel anytime.
          </div>
          <button
            onClick={() => portalSession.mutate()}
            disabled={portalSession.isPending || !data.stripe_customer_id}
            className="inline-flex items-center justify-center px-3 py-2 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-100 disabled:opacity-50 text-sm"
          >
            {portalSession.isPending ? 'Opening…' : 'Manage Billing'}
          </button>
        </div>
      </div>
    </div>
  );
}
