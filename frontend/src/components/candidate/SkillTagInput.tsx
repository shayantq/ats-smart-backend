import { useState, type KeyboardEvent } from "react";

interface SkillTagInputProps {
  skills: string[];
  onChange: (skills: string[]) => void;
}

export default function SkillTagInput({ skills, onChange }: SkillTagInputProps) {
  const [draft, setDraft] = useState("");

  function addSkill() {
    const trimmed = draft.trim();
    if (trimmed.length === 0) return;
    if (skills.includes(trimmed)) {
      setDraft("");
      return;
    }
    onChange([...skills, trimmed]);
    setDraft("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addSkill();
    }
  }

  function removeSkill(skill: string) {
    onChange(skills.filter((item) => item !== skill));
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-sm border border-rule bg-white dark:bg-slate-800 p-3">
      {skills.map((skill) => (
        <span
          key={skill}
          className="flex min-w-0 max-w-full items-center gap-2 rounded-sm bg-wash px-2.5 py-1 text-caption text-ink"
        >
          <bdi className="min-w-0 [overflow-wrap:anywhere]">{skill}</bdi>
          <button
            type="button"
            onClick={() => removeSkill(skill)}
            className="shrink-0 px-1 text-muted hover:text-ink"
            aria-label={`حذف مهارت ${skill}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={addSkill}
        placeholder="مهارت را بنویس و Enter بزن"
        aria-label="افزودن مهارت"
        className="min-w-0 basis-48 flex-1 bg-transparent px-1 py-2 text-sm"
      />
    </div>
  );
}
