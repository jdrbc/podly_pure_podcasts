interface SaveButtonProps {
  onSave: () => void;
  isPending: boolean;
  className?: string;
}

export default function SaveButton({ onSave, isPending, className = '' }: SaveButtonProps) {
  return (
    <div className={`flex items-center justify-end ${className}`}>
      <button
        onClick={onSave}
        className="px-3 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60"
        disabled={isPending}
      >
        {isPending ? 'Saving...' : 'Save Changes'}
      </button>
    </div>
  );
}
