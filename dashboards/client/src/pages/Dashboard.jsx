import useSlots from "../hooks/useSlots";
import SlotCard from "../components/slots/SlotCard";
import DashboardLayout from "../layouts/DashboardLayout";

export default function Dashboard() {
  const {
    slots,
    loading,
    error,
    actionInProgress,
    actions,
    setOptimisticBusy,
  } = useSlots({ pollInterval: 3000 });

  return (
    <DashboardLayout title="LeadForge — Client Dashboard">
      {loading && (
        <div className="h-64 flex items-center justify-center text-sm text-zinc-400">
          Loading slots…
        </div>
      )}

      {error && (
        <div className="h-64 flex items-center justify-center text-sm text-rose-400">
          Failed to load slot data.
        </div>
      )}

      {!loading && !error && (!slots || slots.length === 0) && (
        <div className="h-64 flex items-center justify-center text-sm text-zinc-500">
          No slots provisioned yet.
        </div>
      )}

      {!loading && !error && slots && slots.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 mt-6">
          {slots.map((slot) => (
            <SlotCard
              key={slot.slot_id}
              slot={slot}
              isObserver={false}
              busy={slot.busy || actionInProgress === slot.slot_id}
              onStart={() => {
                setOptimisticBusy(slot.slot_id, true);
                actions.start(slot.slot_id);
              }}
              onStop={() => {
                setOptimisticBusy(slot.slot_id, true);
                actions.stop(slot.slot_id);
              }}
              onRestart={() => {
                setOptimisticBusy(slot.slot_id, true);
                actions.restart(slot.slot_id);
              }}
            />
          ))}
        </div>
      )}
    </DashboardLayout>
  );
}