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
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-300 p-2">
      {skills.map((skill) => (
        <span
          key={skill}
          className="flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700"
        >
          {skill}
          <button
            type="button"
            onClick={() => removeSkill(skill)}
            className="text-blue-500 hover:text-blue-800"
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
        className="min-w-[140px] flex-1 border-none text-sm outline-none"
      />
    </div>
  );
}
