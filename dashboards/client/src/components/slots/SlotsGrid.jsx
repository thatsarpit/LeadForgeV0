import React, { useEffect, useState } from "react";
import SlotCard from "./SlotCard";

export default function SlotsGrid() {
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchSlots() {
      try {
        const res = await fetch("http://localhost:8000/api/slots");
        if (!res.ok) throw new Error("Failed to fetch slots");
        const data = await res.json();
        setSlots(data.slots || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchSlots();
    const interval = setInterval(fetchSlots, 5000); // live observer refresh
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="text-zinc-400 text-sm">
        Loading slot status…
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-red-400 text-sm">
        Error: {error}
      </div>
    );
  }

  if (slots.length === 0) {
    return (
      <div className="text-zinc-500 text-sm">
        No slots available. Waiting for slot initialization…
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {slots.map((slot) => (
        <SlotCard key={slot.id} slot={slot} />
      ))}
    </div>
  );
}
