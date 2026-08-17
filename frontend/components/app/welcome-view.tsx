import { Button } from '@/components/ui/button';

function Lockup() {
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/hire-slice-lockup.svg"
        alt="Hire Slice Pizza Co."
        className="mb-6 block h-24 w-auto dark:hidden"
      />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/hire-slice-lockup-dark.svg"
        alt="Hire Slice Pizza Co."
        className="mb-6 hidden h-24 w-auto dark:block"
      />
    </>
  );
}

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  return (
    <div ref={ref}>
      <section className="bg-background flex flex-col items-center justify-center text-center">
        <Lockup />

        <p className="text-foreground max-w-prose pt-1 leading-6 font-medium">
          Order a pizza by talking to us
        </p>

        <Button
          size="lg"
          onClick={onStartCall}
          className="mt-6 w-64 rounded-full font-mono text-xs font-bold tracking-wider uppercase"
        >
          {startButtonText}
        </Button>
      </section>

      <div className="fixed bottom-5 left-0 flex w-full items-center justify-center">
        <p className="text-muted-foreground max-w-prose pt-1 text-xs leading-5 font-normal text-pretty md:text-sm">
          Prefer the phone? The same agent answers{' '}
          <a href="tel:+18324083180" className="underline">
            (832) 408-3180
          </a>
          .
        </p>
      </div>
    </div>
  );
};
