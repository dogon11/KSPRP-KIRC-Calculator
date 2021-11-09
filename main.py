import json
import random
from functools import cmp_to_key


# Constants for easy modification
# TODO: consider making this a config file.

corner_randomness_factor = 0.1 # number we can tweak to change how far spread corner times are.
crash_base_factor = 1 # number we can tweak to change how likely a crash is.
crash_threshold = 0.5 # seconds apart two cars have to be to trigger a crash check.
pass_threshold = 0.5 # seconds apart two cars have to be to trigger a pass.
defender_penalty = 0.2 # seconds which a defender loses by driving defensively.
attacker_penalty = 0.5 # seconds which an attacker loses by failing to pass.
start_penalty = 0.25 # seconds between cars at the start of the race.
starting_health = 3 # number of mechanical failures that can occur during the race before a car must retire.


# Read in the JSON file containing an object's info, and return
# its parsed contents as a dictionary.
#
# Raises json.JSONDecodeError if file cannot be read as JSON.
# Raises IOError if no such file exists.
def read_json_file(filepath):
    with open(filepath) as info_file:
        json_dict = json.load(info_file)
    
    return json_dict


# Calculate an item's time for a car given car and track info.
# Does not handle passes, defending, crashes, etc.
#
# Formula: Base time + (corner_randomness_factor * sum of differences between a car's ratings and the corner ratings * RNG factor between 0.8 and 1.2)
def item_time(track_item, car):
    # Get a random number between 0.8 and 1.2, up to one decimal place long.
    rng_factor = random.randint(8, 12) / 10.0

    # Sum the differences between the car's relevant ratings and the track item's relevant ratings.
    sum_of_differences = car["power"] - track_item["power"] + car["handling"] - track_item["handling"]

    return track_item["base_time"] + (corner_randomness_factor * sum_of_differences * rng_factor)


# Given two cars' current race times, 
# determine if the first car crashed.
# Each true check requires checking each car separately.
#
# Formula: probability = crash_base_factor * (time difference / -(crash_threshold) + 1)
def crash_check(car_a_time, car_b_time):
    probability = crash_base_factor * (abs(car_a_time - car_b_time) / (-1 * crash_threshold) + 1)
    return True if random.randint(0, 100) <= (probability * 100) else False


# Given a car and a track,
# run the reliability check.
# True equals a failed check.
def reliability_check(car, track_rating):
    percent_difference = car["reliability"] / track_rating
    return True if random.randint(0, 100) <= (percent_difference * 100) else False


# Given the field of cars, determine the 
# position of the last running car.
# This will be used when adding new DNFs.
def last_running(cars):
    field = sorted(cars, key=lambda car: car["position"])
    for car in field:
        if car["health"] < 1:
            return car["position"] - 1
        else:
            continue


# Use this to update the positions of all cars.
# Ties are broken by race_time, where lower = earlier.
# None race_times are always DNF.
def update_positions(cars):

    # If 1, car_a is behind car_b, else -1 car_b is ahead of car_a.
    def compare_car_positions(car_a, car_b):
        if car_a["race_time"] is None:
            if car_b["race_time"] is None:
                if car_a["position"] == car_b["position"]:
                    # Pick one to break the tie randomly.
                    if random.randint(1, 2) == 1:
                        return 1
                    else:
                        return -1
                elif car_a["position"] >= car_b["position"]:
                    return 1
                else:
                    return -1
            else:
                return 1
        elif car_b["race_time"] is None:
            return -1
        else:
            # Make the comparison based on race_time.
            if car_a["race_time"] < car_b["race_time"]:
                return -1
            else:
                return 1
    
    # Sort the field using our custom comparator function.
    field = sorted(cars, key=cmp_to_key(compare_car_positions))

    # Now re-number the field.
    for i in range(1, len(field) + 1):
        field[i - 1]["position"] = i
    
    # Return the sorted, updated field.
    return field


# Given the field of cars plus a track item,
# calculate everyone's times, run the crash checks,
# and if the track item is the end of a sector,
# run the reliability checks.
# Return the field of cars with the changed information.
def run_track_item(cars, track_item, track_rating):

    # Step 1: Calculate the lap times after going through the corner.
    for car in cars:
        if car["health"] > 0:
            car_item_time = item_time(track_item, car)
            car["race_time"] = car["race_time"] + car_item_time
    
    # Step 2: Figure out if any passes occurred or need to be checked.
    field = sorted(cars, key=lambda car: car["position"])
    for i in range(1, len(field)):
        car_a = field[i] # Attacker.
        car_b = field[i - 1] # Defender.

        # Check if there was a pass, a defense + crash check, or nothing.
        if car_b["race_time"] - car_a["race_time"] > pass_threshold:

            # Clean pass, switch positions.
            car_a_pos = car_a["position"]
            car_a["position"] = car_b["position"]
            car_b["position"] = car_a_pos
        
        elif car_b["race_time"] - car_a["race_time"] < pass_threshold and car_b["race_time"] - car_a["race_time"] > 0:

            # Failed pass. Add time penalties.
            car_b["race_time"] = car_b["race_time"] + defender_penalty # Defender penalty.
            car_a["race_time"] = car_b["race_time"] + attacker_penalty # Attacker penalty.

            # Run a crash check per car.

            if crash_check(car_a["race_time"], car_b["race_time"]):
                # A crashed.
                car_a["health"] = 0
                car_a["race_time"] = None
                car_a["position"] = last_running(field)
                field = update_positions(field)
            
            if crash_check(car_b["race_time"], car_a["race_time"]):
                # B crashed.
                car_b["health"] = 0
                car_b["race_time"] = None
                car_b["position"] = last_running(field)
                field = update_positions(field)
            
        # Else no pass occurred, and the field can be left alone.

    # Step 3: Reliability checks at end of sector.
    if track_item["is_sector_end"]:
        # Per car, run the reliability check.
        i = 0
        while i < len(field):
            car = field[i]
            # Don't check cars that have already retired from the race.
            if car["race_time"] is not None:
                if reliability_check(car, track_rating):
                    # Car failed. Update their health. Healths of zero = DNF.
                    car["health"] = car["health"] - 1
                    if car["health"] < 1:
                        # Car retires.
                        car["race_time"] = None
                        car["position"] = last_running
                        field = update_positions(field)
                        continue # Skip the iterator, since the car in the current position is no longer there.
            
            # If we haven't hit continue yet, no cars have changed position, so check the next car.
            i += 1
    
    # Step 4: Return the modified field.
    return field

# Given a field of entrants, populated,
# and the track, run a race with the given
# number of laps. 
def run_race(cars, track, num_laps):
    field = cars
    # For each lap...
    for i in range(1, num_laps):
        # For each track element...
        for track_item in track["items"].keys():
            # Run the track element.
            field = run_track_item(field, track["items"][track_item], track["relability_rating"])
    
    # Once the race is over, return the field and get their finishing order.
    return update_positions(field)


# Given a field of entrants, run qualifying.
# Everyone gets one lap, each run separately,
# and we determine starting position based on this lap.
# Return a dictionary of cars and spots to
# be used to assess the starting time penalties.
def run_qualifying(cars, track):
    # Run each car in a field on its own through one lap and save the laptime.
    qualy_laps = {}
    for car in cars:
        for track_item in track["items"].keys():
            # Run the track element.
            field = run_track_item([car], track["items"][track_item], 1) # No breakdowns in qualy.
            qualy_laps[field[0]["car_number"]] = field[0]["race_time"]
    
    # Next go across the laptimes and assign starting orders.
    results = {}
    position_counter = 1
    while len(qualy_laps) > 0:
        next_car = min(qualy_laps, key=qualy_laps.get)
        results[next_car] = position_counter
        del qualy_laps[next_car]
    
    # Return the dict of car numbers to starting order.
    return results


# Run a race weekend.
# Given a list of cars and the track,
# populate the extra car fields,
# run qualifying,
# apply the qualifying start time penalties,
# run the race,
# and output the results.
def run_race_weekend(cars, track, num_laps):
    # Populate the fields for the cars.
    for car in cars:
        car["race_time"] = 0.0
        car["position"] = 0
        car["health"] = starting_health

    qualy_results = run_qualifying(cars, track)

    # For each car in qualy results, set their starting race_time and position.
    for qualified_car in qualy_results.keys():
        # Find the matching car by the number.
        for car in cars:
            if qualified_car == car["car_number"]:
                car["position"] = qualy_results["qualified_car"]
                car["race_time"] = (start_penalty * qualy_results["qualified_car"]) - start_penalty # Quarter-second penalty for each position off pole at start.

    # Now that the cars are set up with their qualifying results, run the race.
    return run_race(cars, track, num_laps)


# Managing function to run everything. 
# Gets input from the user,
# reads the input files,
# calls run_race_weekend.
def main():
    # Print introductory messages and get the files.
    print("Welcome to the IKMO race weekend calculator!")
    car_path = input("Please type the filepath to the JSON file where the cars are saved.")
    track_path = input("please type the filepath to the JSON file where the track is saved.")

    # Load the cars and track.
    # TODO: Decide if we want to catch exceptions and print messages or let it kill stuff.
    cars = read_json_file(car_path)
    track = read_json_file(track_path)

    # Get the number of laps to run.
    continue_check = False
    while not continue_check:
        try:
            num_laps = int(input("Please type the number of laps you'd like to race."))
        except ValueError:
            print("Please try again. Only insert whole integer numbers.")
            continue
        
        # Estimate a race time.
        lap_time_estimate = 0
        for item_id in track["items"].keys():
            lap_time_estimate += track["items"][item_id]["base_time"]
        lap_time_estimate *= num_laps

        is_good = input(f"The estimated race time is {str(lap_time_estimate / 60.0)} minutes long.\nWould you like to continue with this time? (yes/no)")
        if "yes" in is_good.lower():
            continue_check = True
            print(f"Continuing with {str(num_laps)} laps.")

    # Run the race weekend..
    race_results = run_race_weekend(cars, track, num_laps)

    print(str(race_results))
