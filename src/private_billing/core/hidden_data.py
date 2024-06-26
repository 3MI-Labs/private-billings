from __future__ import annotations
from openfhe import Ciphertext
from .hiding import PublicHidingContext
from .serialize import Pickleable
from .hidden_bill import HiddenBill
from .cycle import CycleContext, CycleID, SharedCycleData, ClientID
from .utils import max_vector, vector
from dataclasses import dataclass


@dataclass
class HiddenData(Pickleable):
    """
    :param client: id of client owning this data
    :param cycle_id: id of cycle to which this data belongs
    :param consumptions: Encrypted consumption, per timeslot
    :param supplies: Encrypted supply, per timeslot
    :param accepted_consumer_flags: Flags indicating timeslots for peer was accepted to peer-to-peer trade as consumer.
    :param accepted_producer_flags: Flags indicating timeslots for peer was accepted to peer-to-peer trade as producer.
    :param positive_deviation_flags: Flags indicating timeslots with negative deviation
    :param masked_individual_deviations: Deviation information, masked
    :param masked_p2p_consumer_flags: Flag indicating timeslots in which this user was a p2p consumer, masked.
    :param masked_p2p_producer_flags: Flag indicating timeslots in which this user was a p2p producer, masked.
    :param phc: context under which the information is encrypted/hidden
    """

    client: ClientID
    cycle_id: CycleID
    consumptions: Ciphertext
    supplies: Ciphertext
    accepted_consumer_flags: Ciphertext
    accepted_producer_flags: Ciphertext
    positive_deviation_flags: Ciphertext
    masked_individual_deviations: vector[float]
    masked_p2p_consumer_flags: vector[float]
    masked_p2p_producer_flags: vector[float]
    phc: PublicHidingContext

    def check_validity(self, cyc: CycleContext) -> bool:
        # Check all encrypted data is correct
        assert isinstance(self.consumptions, Ciphertext)
        assert isinstance(self.supplies, Ciphertext)
        assert isinstance(self.accepted_consumer_flags, Ciphertext)
        assert isinstance(self.accepted_producer_flags, Ciphertext)
        assert isinstance(self.positive_deviation_flags, Ciphertext)
        assert isinstance(self.phc, PublicHidingContext)

        # Check all masked data is correct
        assert len(self.masked_individual_deviations) == cyc.cycle_length
        assert len(self.masked_p2p_consumer_flags) == cyc.cycle_length
        assert len(self.masked_p2p_producer_flags) == cyc.cycle_length

    @staticmethod
    def unmask_data(cycle_data: list[HiddenData]) -> SharedCycleData:
        """
        Unmask hidden data.

        :param cycle_data: data that should be combined to be revealed
        :raises ValueError: when an empty list is provided
        :return: shared cycle data
        """
        if len(cycle_data) == 0:
            raise ValueError("invalid cycle_data")

        vec_len = len(cycle_data[0].masked_individual_deviations)
        total_deviations = vector.new(vec_len)
        consumer_counts = vector.new(vec_len)
        producer_counts = vector.new(vec_len)

        for datum in cycle_data:
            total_deviations += datum.masked_individual_deviations
            consumer_counts += datum.masked_p2p_consumer_flags
            producer_counts += datum.masked_p2p_producer_flags

        return SharedCycleData(total_deviations, consumer_counts, producer_counts)

    def compute_hidden_bill(
        self, scd: SharedCycleData, cyc: CycleContext
    ) -> HiddenBill:
        """Compute hidden bill based on this user data."""

        # === BUG BYPASS ===
        # Activate relinearization key.
        # More info: see PublicHidingContext class
        self.phc.activate_keys()

        # Bump zero-counts to prevent division-by-zero problems.
        # Note that this does not affect the bills or rewards:
        # if for a given timeslot either count is 0, the positive_deviation_flags and negative_deviation_flags at that
        # timeslot for all consumers/producers must be 0 too in this scenario, these total_ values do not contribute
        # to any bill/reward.
        total_p2p_consumers = max_vector(scd.total_p2p_consumers, 1.0)
        total_p2p_producers = max_vector(scd.total_p2p_producers, 1.0)

        # Create rejected a dual to the accepted mask
        rejected_consumer_flags = self.phc.invert_flags(self.accepted_consumer_flags)
        rejected_producer_flags = self.phc.invert_flags(self.accepted_producer_flags)

        # CASE: Client not accepted for P2P trading
        #  -> pay retail price for the consumption
        #  -> get feed-in tarif for the production
        bill_no_p2p = self.phc.scale(self.consumptions, cyc.retail_prices)
        bill_no_p2p = self.phc.multiply(bill_no_p2p, rejected_consumer_flags)
        reward_no_p2p = self.phc.scale(self.supplies, cyc.feed_in_tarifs)
        reward_no_p2p = self.phc.multiply(reward_no_p2p, rejected_producer_flags)

        # CASE: Client was accepted for P2P trading
        base_bill = self.phc.scale(self.consumptions, cyc.trading_prices)
        base_reward = self.phc.scale(self.supplies, cyc.trading_prices)

        # CASE: TD < 0, individual dev > 0
        # consumer gets a supplement
        # they buy their portion of what was used too much against retail price.
        # bill = (consumption + TD / nr_p2p_consumers) * tradingPrice - TD / nr_p2p_consumers * retailPrice
        #      = consumption * tradingPrice + TD / nr_p2p_consumers * (tradingPrice - retailPrice)
        #      = baseBill + TD / nr_p2p_consumers * (trading price - retail_price)
        # hence,
        # supplement = TD / nr_p2p_consumers * (trading price - retail_price)
        bill_supplement = (
            (cyc.trading_prices - cyc.retail_prices)
            * scd.total_deviations
            / total_p2p_consumers
        )
        bill_supplement *= scd.negative_total_deviation_flags
        bill_supplement_ct = self.phc.scale(self.positive_deviation_flags, bill_supplement)

        # CASE: TD > 0, individual dev > 0
        # producers get a penalty
        # they sell their portion of what was produced too much against feedin tarif
        # reward = (supply - TD / nr_p2p_producers) * tradingPrice + TD / nr_p2p_producers * feedInTarif
        #        = supply * tradingPrice + (TD / nr_p2p_producers * (feedInTarif - tradingPrice)
        #        = baseReward + (TD / nr_p2p_producers * (feedInTarif - tradingPrice)
        # hence,
        # penalty = (TD / nr_p2p_producers) * (feedInTarif - tradingPrice)
        #
        # Note that the penalty is negative, since feedInTarif is assumed to be < tradingPrice
        reward_penalty = (
            (cyc.feed_in_tarifs - cyc.trading_prices)
            * scd.total_deviations
            / total_p2p_producers
        )
        reward_penalty *= scd.positive_total_deviation_flags
        reward_penalty_ct = self.phc.scale(self.positive_deviation_flags, reward_penalty)

        # Aggregating the P2P cases
        bill_p2p = base_bill + bill_supplement_ct
        bill_p2p = self.phc.multiply(bill_p2p, self.accepted_consumer_flags)

        reward_p2p = base_reward + reward_penalty_ct
        reward_p2p = self.phc.multiply(reward_p2p, self.accepted_producer_flags)

        # Aggregating P2P and no-P2P cases
        bill = bill_p2p + bill_no_p2p
        reward = reward_p2p + reward_no_p2p

        return HiddenBill(self.cycle_id, bill, reward)
