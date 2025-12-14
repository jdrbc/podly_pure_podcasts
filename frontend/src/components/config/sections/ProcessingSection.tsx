import { useConfigContext } from '../ConfigContext';
import { Section, Field, SaveButton } from '../shared';

export default function ProcessingSection() {
  const { pending, setField, handleSave, isSaving } = useConfigContext();

  if (!pending) return null;

  return (
    <div className="space-y-6">
      <Section title="Processing">
        <Field label="Number of Segments per Prompt">
          <input
            className="input"
            type="number"
            value={pending?.processing?.num_segments_to_input_to_prompt ?? 30}
            onChange={(e) =>
              setField(['processing', 'num_segments_to_input_to_prompt'], Number(e.target.value))
            }
          />
        </Field>
      </Section>

      <SaveButton onSave={handleSave} isPending={isSaving} />

      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </div>
  );
}
