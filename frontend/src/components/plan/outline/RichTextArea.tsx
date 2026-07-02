import { useEffect } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Bold, Italic, List } from "lucide-react";
import { clsx } from "clsx";

interface RichTextAreaProps {
  value: string;           // HTML string
  onChange: (html: string) => void;
  onBlur?: () => void;
  placeholder?: string;
  className?: string;
  editable?: boolean;
}

export default function RichTextArea({
  value,
  onChange,
  onBlur,
  placeholder,
  className,
  editable = true,
}: RichTextAreaProps) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: value || "",
    editable,
    onUpdate: ({ editor }) => {
      const html = editor.isEmpty ? "" : editor.getHTML();
      onChange(html);
    },
    onBlur: () => onBlur?.(),
    editorProps: {
      attributes: {
        class: "outline-none min-h-0 leading-relaxed",
      },
    },
  });

  // Sync external value changes (e.g. chapter prop update) without clobbering cursor
  useEffect(() => {
    if (!editor) return;
    const current = editor.isEmpty ? "" : editor.getHTML();
    if (current !== value) {
      editor.commands.setContent(value || "", { emitUpdate: false });
    }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync editable flag
  useEffect(() => {
    if (!editor) return;
    editor.setEditable(editable);
  }, [editor, editable]);

  if (!editor) return null;

  const toolbarBtn = (active: boolean, onClick: () => void, title: string, icon: React.ReactNode) => (
    <button
      type="button"
      onMouseDown={(e) => { e.preventDefault(); onClick(); }}
      title={title}
      className={clsx(
        "rounded p-0.5 transition-colors",
        active
          ? "bg-accent/20 text-accent"
          : "text-ink-muted hover:text-ink-secondary hover:bg-surface-hover"
      )}
    >
      {icon}
    </button>
  );

  return (
    <div className={clsx("flex flex-col overflow-hidden", className)}>
      {/* Toolbar */}
      <div className="flex-shrink-0 flex items-center gap-0.5 border-b border-surface-border px-1 py-0.5">
        {toolbarBtn(
          editor.isActive("bold"),
          () => editor.chain().focus().toggleBold().run(),
          "Bold",
          <Bold className="h-3 w-3" />
        )}
        {toolbarBtn(
          editor.isActive("italic"),
          () => editor.chain().focus().toggleItalic().run(),
          "Italic",
          <Italic className="h-3 w-3" />
        )}
        {toolbarBtn(
          editor.isActive("bulletList"),
          () => editor.chain().focus().toggleBulletList().run(),
          "Bullet list",
          <List className="h-3 w-3" />
        )}
      </div>

      {/* Editor area */}
      <div className="relative flex-1 min-h-0 overflow-y-auto px-1.5 py-1">
        {editor.isEmpty && placeholder && (
          <span className="pointer-events-none absolute left-1.5 top-1 text-[11px] text-ink-muted/60 select-none">
            {placeholder}
          </span>
        )}
        <EditorContent
          editor={editor}
          className="h-full text-[11px] [&_.ProseMirror]:min-h-0 [&_.ProseMirror_ul]:list-disc [&_.ProseMirror_ul]:pl-4 [&_.ProseMirror_ul]:my-0.5 [&_.ProseMirror_li]:my-0 [&_.ProseMirror_p]:my-0 [&_.ProseMirror_strong]:font-semibold [&_.ProseMirror_em]:italic"
        />
      </div>
    </div>
  );
}
