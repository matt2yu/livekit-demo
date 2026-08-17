import { OrderFeed } from '@/components/admin/order-feed';

export const metadata = {
  title: 'Hire Slice — kitchen',
};

export default function AdminPage() {
  return (
    <main className="mx-auto max-w-7xl px-6 pt-24 pb-16">
      <h1 className="mb-1 text-2xl font-bold">Kitchen</h1>
      <p className="text-muted-foreground mb-8 text-sm">Orders as they are placed. Newest first.</p>
      <OrderFeed />
    </main>
  );
}
