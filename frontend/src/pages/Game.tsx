import { useParams } from 'react-router-dom';

import { GameBoard } from '@/components/GameBoard';

/** Today's puzzle, or a past date when one is supplied in the URL. */
export function Game() {
  const { date } = useParams<{ date?: string }>();

  const heading = date
    ? new Date(`${date}T00:00:00`).toLocaleDateString(undefined, {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      })
    : undefined;

  return <GameBoard gameDate={date} heading={heading} />;
}
