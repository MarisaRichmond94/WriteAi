import { useAppStore } from "../../store/useAppStore";
import BookItem from "./BookItem";
import { Loader2 } from "lucide-react";

export default function BookList() {
  const { books, booksLoading } = useAppStore();

  if (booksLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-ink-muted" />
      </div>
    );
  }

  if (books.length === 0) {
    return (
      <p className="px-4 py-4 text-xs text-ink-muted">
        No books found. Check your BOOKS_DIR setting.
      </p>
    );
  }

  return (
    <ul className="space-y-0.5 px-2">
      {books.map((book) => (
        <BookItem key={book.id} book={book} />
      ))}
    </ul>
  );
}
