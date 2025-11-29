interface TestButtonProps {
  onClick: () => void;
  label: string;
  className?: string;
}

export default function TestButton({ onClick, label, className = '' }: TestButtonProps) {
  return (
    <div className={`flex justify-center ${className}`}>
      <button
        onClick={onClick}
        className="mt-2 px-3 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
      >
        {label}
      </button>
    </div>
  );
}
