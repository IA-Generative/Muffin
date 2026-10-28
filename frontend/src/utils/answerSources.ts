// An answer that rests on evidence but shows no source (#402): the model consulted excerpts and cited none of them. The
// sources the chat shows are the ones the answer cites, so such an answer would otherwise look as if it came from nowhere
// - and the user must see that they cannot check it, instead of nothing.
export function answerHasNoSource(consulted: readonly unknown[] | null | undefined, shown: readonly unknown[] | undefined): boolean {
  return !!consulted?.length && !shown?.length
}
