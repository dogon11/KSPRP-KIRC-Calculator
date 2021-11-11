import json
import random
import logging
import sys
from functools import cmp_to_key


# Constants for easy modification
# TODO: consider making this a config file.

sum_of_differences_weight = 2 # number we divide the sum of differences by to decide how important it is to laptimes.
corner_randomness_factor = 0.1 # number we can tweak to change how far spread corner times are.
corner_base_rng_val = 0.6 # Lowest value the corner-time RNG can modify the statistics modifiers by.
corner_highest_rng_val = 1.4 # Highest value the corner-time RNG can modify the statistics modifiers by.
crash_base_factor = 0.01 # number we can tweak to change how likely a crash is.
crash_threshold = 0.25 # seconds apart two cars have to be to trigger a crash check.
pass_threshold = 0.4 # seconds apart two cars have to be to trigger a pass.
skill_threshold = 0.25 # seconds apart where a skilled driver can make a pass.
defender_penalty = 0.1 # seconds which a defender loses by driving defensively.
attacker_penalty = 0.4 # seconds which an attacker loses by failing to pass.
start_penalty = 0.2 # seconds between cars at the start of the race.
starting_health = 3 # number of mechanical failures that can occur during the race before a car must retire.
failure_factor = 1.10 # modifier to odds of mechanical failures, adjustable to increase/reduce retirement rates. Higher means less, lower means more.
max_breakdown_resistance = 0.9 # Maximum probability of dodging a mechanical breakdown


# Global variables for tracking statistics.
successful_passes = 0
unsuccessful_passes = 0
lead_changes = 0
crashes = 0
retirements = 0


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
    rng_factor = random.randint((corner_base_rng_val * 10), (corner_highest_rng_val * 10)) / 10.0

    # Sum the differences between the car's relevant ratings and the track item's relevant ratings.
    sum_of_differences = (track_item["power"] - car["power"] + track_item["handling"] - car["handling"]) / sum_of_differences_weight
    if sum_of_differences == 0.0:
        sum_of_differences = 0.1 # Prevent multiply by zero by assigning a minimum difference. This keeps some variability in lap times.

    item_time = track_item["base_time"] + (corner_randomness_factor * sum_of_differences * rng_factor)
    logging.debug(f"Car {car['car_number']}: {str(track_item['base_time'])} + ({str(corner_randomness_factor)} * {str(sum_of_differences)} * {str(rng_factor)}) = {str(item_time)}")
    return item_time


# Given two cars' current race times, 
# determine if the first car crashed.
# Each true check requires checking each car separately.
#
# Formula: probability = crash_base_factor * (time difference / -(crash_threshold) + 1)
def crash_check(car_a_time, car_b_time):
    logging.debug("Checking if car A and B have caused a crash.")
    probability = crash_base_factor * (abs(car_a_time - car_b_time) / (-1 * crash_threshold) + 1)
    #print(f"Crash probability: {str(probability * 100)}") # DEBUG
    check_num = random.randint(0, 100)
    #print(f"Check num: {str(check_num)}") # DEBUG
    return True if check_num < (probability * 100) else False


# Given a car and a track,
# run the reliability check.
# True equals a failed check.
def reliability_check(car, track_rating):
    percent_difference = failure_factor * (car["reliability"] / track_rating)
    if percent_difference >= max_breakdown_resistance:
        percent_difference == max_breakdown_resistance
    return True if random.randint(1, 100) > (percent_difference * 100) else False


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

    logging.debug("Sorting and re-ordering field.")

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


# Return a string containing the current field order.
def get_current_order(cars):
    return_string = ""
    field = sorted(cars, key=lambda car: car["position"])
    for car in field:
        return_string = return_string + "\t" + car['car_number'] + ", " + str(car['race_time']) + "\n"
    return return_string


# Select the car with the given position.
def get_position(cars, position):
    if position < 1:
        return None
    else:
        for car in cars:
            if car['position'] == position:
                return car
        return None


# Run a pass check through the field.
# Separated to keep like code together.
# Also lets me change how often pass checks are made.
def run_pass_check(cars):

    global successful_passes
    global unsuccessful_passes
    global lead_changes
    global crashes

    #Figure out if any passes occurred or need to be checked.
    field = sorted(cars, key=lambda car: car["position"])
    logging.debug(f"Order before pass:\n{get_current_order(field)}") # DEBUG
    for i in range(1, len(field)):
        pass_happened = False
        car_a = field[i] # Attacker.
        car_b = field[i - 1] # Defender.

        # First, make sure these cars are actually running. Continue if one or more of them aren't.
        if car_a["race_time"] is None or car_b["race_time"] is None:
            continue

        # Check if there was a pass, a defense + crash check, or nothing.
        gap = car_b["race_time"] - car_a["race_time"]
        logging.debug(f"Checking for pass between {car_a['car_number']} time {str(car_a['race_time'])} and {car_b['car_number']} time {str(car_b['race_time'])}: {str(gap)}") # DEBUG
        if gap > pass_threshold:

            # Clean pass, switch positions.
            logging.debug(f"Car {car_b['car_number']} was passed by car {car_a['car_number']}.")
            car_a_pos = car_a["position"]
            car_a["position"] = car_b["position"]
            car_b["position"] = car_a_pos
            print(f"Wow, look at that! {car_a['driver_name']} in the {car_a['car_number']} just passed {car_b['car_number']} for position {str(car_a_pos - 1)}!")
            field = update_positions(field)
            successful_passes += 1
            pass_happened = True
        
        elif gap < pass_threshold and gap >= 0:

            # Failed pass. Add time penalties.
            logging.debug(f"Car {car_b['car_number']} defending from car {car_a['car_number']}.")
            print(f"And car {car_b['car_number']} has to defend against from a pass from car {car_a['car_number']}!")
            unsuccessful_passes += 1

            # Run a crash check per car.
            a_crashed = False
            b_crashed = False
            car_a_time = car_a["race_time"]
            car_b_time = car_b["race_time"]
            gap = abs(car_a_time - car_b_time)

            if gap <= crash_threshold and crash_check(car_a_time, car_b_time):
                # A crashed.
                a_crashed = True
                logging.debug(f"Car {car_a['car_number']} crashed out!")
                car_a["health"] = 0
                car_a["race_time"] = None
                car_a["position"] = last_running(field)
                field = update_positions(field)
            
            if gap <= crash_threshold and crash_check(car_b_time, car_a_time):
                # B crashed.
                b_crashed = True
                logging.debug(f"Car {car_b['car_number']} crashed out!")
                car_b["health"] = 0
                car_b["race_time"] = None
                car_b["position"] = last_running(field)
                field = update_positions(field)
            
            if a_crashed and b_crashed:
                print(f"Oh now they've come together passing! {car_a['driver_name']} went too deep on the brakes and ran wide, collecting {car_b['driver_name']} with him! They're both out of the race!")
                unsuccessful_passes += 1
                crashes += 1
            elif b_crashed:
                print(f"Look, {car_b['driver_name']} failed to defend from passing and ran wide! And they've spun across the outside of the track and hit the barrier! They're out of the race!")
                unsuccessful_passes += 1
                crashes += 1
            elif a_crashed:
                print(f"Oh no! {car_a['driver_name']} goes in too deep while passing! {car_b['driver_name']} squeezes them to the inside of the track! They've hit a sausage kerb and spun off! They're stuck, and that's the end of their race!")
                unsuccessful_passes += 1
                crashes += 1
            else:
                """
                print(f"What a clean defense from passing by {car_b['driver_name']}! Absolutely textbook. {car_a['driver_name']} is still right behind, they might mount an attack into the next corner!")
                car_b["race_time"] = car_b["race_time"] + defender_penalty # Defender penalty.
                car_a["race_time"] = car_b["race_time"] + attacker_penalty # Attacker penalty.
                unsuccessful_passes += 1
                """
                #"""
                # Run driver skills against each other if the threshold is close enough, whoever has the higher driver skill wins the pass.
                if car_a['race_time'] - car_b['race_time'] < skill_threshold and car_a['driver_skill'] > car_b['driver_skill']:
                    # Car A makes the pass on skill.
                    logging.debug(f"Car {car_b['car_number']} was passed by car {car_a['car_number']} on driver skill.")
                    car_a_pos = car_a["position"]
                    car_a["position"] = car_b["position"]
                    car_b["position"] = car_a_pos
                    print(f"That's a classic crossover manuever by {car_a['driver_name']} in the {car_a['car_number']}! They've successfully passed {car_b['car_number']} for position {str(car_a_pos - 1)}!")
                    successful_passes += 1
                    pass_happened = True
                else:
                    # Car B defends on skill.
                    print(f"What a clean defense from passing by {car_b['driver_name']}! Absolutely textbook. {car_a['driver_name']} is still right behind, they might mount an attack into the next corner!")
                    car_b["race_time"] = car_b["race_time"] + defender_penalty # Defender penalty.
                    car_a["race_time"] = car_b["race_time"] + attacker_penalty # Attacker penalty.
                    unsuccessful_passes += 1
                #"""
        if pass_happened:
            # Check if we passed the next car ahead by the pass margin. If not, we apply the skill threshold as a penalty.
            # Get the current car and check the gap versus the next car in line.
            next_car = get_position(field, car_a['position'] - 1)
            while next_car is not None:
                if next_car['race_time'] - car_a['race_time'] > pass_threshold:
                    # Extra pass on the next car.
                    logging.debug(f"Car {car_b['car_number']} was passed by car {car_a['car_number']} on driver skill.")
                    car_a_pos = car_a["position"]
                    car_a["position"] = next_car["position"]
                    next_car["position"] = car_a_pos
                    print(f"Wow, {car_a['driver_name']} is really picking up the pace, he managed to pass {next_car['driver_name']} as well that lap!")
                    next_car = get_position(field, car_a['position'] - 1)
                else:
                    break

            
            if next_car is not None:
                if next_car['race_time'] - car_a['race_time'] <= pass_threshold and next_car['race_time'] - car_a['race_time'] >= 0:
                    # Does not meet pass threshold.
                    car_a['race_time'] = car_a['race_time'] - skill_threshold
            logging.debug(f"order after pass:\n {get_current_order(field)}") # DEBUG

        # Else no pass occurred, and the field can be left alone.
    
    return field


# Given the field of cars plus a track item,
# calculate everyone's times, run the crash checks,
# and if the track item is the end of a sector,
# run the reliability checks.
# Return the field of cars with the changed information.
def run_track_item(cars, track_item, track_rating):

    global lead_changes
    global retirements

    # Step 1: Calculate the lap times after going through the corner.
    for car in cars:
        logging.debug(f"Car {car['car_number']} is going through the track item.")
        if car["health"] > 0:
            car_item_time = item_time(track_item, car)
            logging.debug(f"Car {car['car_number']} has an item time of {str(car_item_time)}")
            car["race_time"] = car["race_time"] + car_item_time
            logging.debug(f"Car {car['car_number']} race time before passes = {car['race_time']}")
    
    # Step 2: Run pass check through the field.
    #field = run_pass_check(cars)

    # Step 3: Reliability checks at end of lap.
    if track_item["is_lap_end"]:
        # Per car, run the reliability check.
        for car in cars:
            logging.debug(f"Running reliability check for car {car['car_number']}.")
            # Don't check cars that have already retired from the race.
            if car["race_time"] is not None:
                if reliability_check(car, track_rating):
                    # Car failed. Update their health. Healths of zero = DNF.
                    logging.debug(f"Car {car['car_number']} failed their reliability check, and has {car['health'] - 1} health remaining.")
                    print(f"There's a commotion in the pit lane from the garage of car {car['car_number']}, it sounds like the engineers have spotted a mechanical breakdown on the car! Hopefully they can continue racing.")
                    car["health"] = car["health"] - 1
                    if car["health"] < 1:
                        # Car retires.
                        logging.debug(f"Car {car['car_number']} has retired from the race for mechanical failures.")
                        print(f"We're hearing that car {car['car_number']} is retiring for a mechanical breakdown! They've pulled off to the side of the track, and the marshals are moving to remove the car. That must be so disappointing!")
                        car["race_time"] = None
                        if car["position"] == 1:
                            lead_changes += 1
                        car["position"] = last_running(cars)
                        cars = update_positions(cars)
                        retirements += 1
                        logging.debug(f"retirements: {str(retirements)}")
    
    # Step 4: Return the modified field.
    return cars

# Given a field of entrants, populated,
# and the track, run a race with the given
# number of laps. 
def run_race(cars, track, num_laps):
    field = cars
    # For each lap...
    for i in range(1, num_laps + 1):
        print(f"\nIt's now lap {i} here at the Grand Prix!")
        logging.info(f"Running lap {str(i)}/{str(num_laps)}")
        # For each track element...
        for track_item in track["items"].keys():
            logging.debug(f"Running track element {str(track_item)}.")
            # Run the track element.
            # print(f"The field is now going into turn {track_item}!") # TODO Remove.
            field = run_track_item(field, track["items"][track_item], track["reliability_rating"])
        
        # At the end of the lap, run pass checks.
        field = run_pass_check(field)

        print(f"At the end of lap {i}, the current standings are:")
        field_counter = 0
        if i != num_laps:
            while field_counter < len(field):
                current_car = field[field_counter]
                print(f"\tCar: {current_car['car_number']}")
                print(f"\t\tDriver: {current_car['driver_name']}")
                print(f"\t\tGap: {'0.0' if current_car['race_time'] is None or field_counter == 0 else str(round(current_car['race_time'] - field[field_counter - 1]['race_time'], 2))}")
                field_counter += 1

    
    # Once the race is over, return the field and get their finishing order.
    logging.info("Race over.")
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
        logging.debug("Qualifying car:\n" + str(car))
        for track_item in track["items"].keys():
            # Run the track element.
            field = run_track_item([car], track["items"][track_item], 1) # No breakdowns in qualy.
            logging.debug("Current time for car: " + str(field[0]["race_time"]))
            qualy_laps[field[0]["car_number"]] = field[0]["race_time"]
        logging.debug("Final time for current car: " + str(qualy_laps[field[0]["car_number"]]))
        print(f"And car {car['car_number']} just set a laptime of {str(qualy_laps[field[0]['car_number']])}!")
    
    # Next go across the laptimes and assign starting orders.
    logging.debug("Field results =\n" + str(qualy_laps))
    results = {}
    position_counter = 1
    while len(qualy_laps) > 0:
        next_car = min(qualy_laps, key=qualy_laps.get)
        results[next_car] = position_counter
        logging.debug(f"Car position {str(position_counter)} = {next_car}")
        del qualy_laps[next_car]
        position_counter += 1
    
    # Return the dict of car numbers to starting order.
    logging.debug("Qualifying results =\n" + str(results))
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

    logging.info("Running qualifying.")
    print("We're down here now on the pit wall, waiting for the first car to go out. Looks like they're waving the first, so we're now starting qualifying!\n")
    qualy_results = run_qualifying(cars, track)

    # For each car in qualy results, set their starting race_time and position.
    for qualified_car in qualy_results.keys():
        # Find the matching car by the number.
        for car in cars:
            if qualified_car == car["car_number"]:
                car["position"] = qualy_results[qualified_car]
                car["race_time"] = (start_penalty * qualy_results[qualified_car]) - start_penalty # Quarter-second penalty for each position off pole at start.

    logging.debug("Field after qualifying:\n" + str(cars))
    print("There were some impressive laps set out there in qualifying today, hopefully they translate to some exciting racing! Your field for today's race:")
    for car in cars:
        print(f"\tCar #: {str(car['car_number'])}\n\t\tDriver: {car['driver_name']}\n\t\tPosition: {str(car['position'])}")

    # Now that the cars are set up with their qualifying results, run the race.
    logging.info("Running race.")
    print("\nNow let's get down to the starting grid! The cars are lined up, and we're almost ready to drop the green flag!")
    return run_race(cars, track, num_laps)


# Managing function to run everything. 
# Gets input from the user,
# reads the input files,
# calls run_race_weekend.
def main():
    print("Welcome to the IKMO race weekend calculator!")

    logging.basicConfig(filename='log.txt', filemode='w', format='%(levelname)s: %(message)s')

    # Print introductory messages and get the files.
    logging.info("Initializing calculator, printing welcome messages.")

    random.seed()

    logging.debug("Getting user input for car_path.")
    car_path = input("Please type the filepath to the JSON file where the cars are saved.")
    logging.debug(f"car_path = {str(car_path)}")

    logging.debug("Getting user input for track_path.")
    track_path = input("please type the filepath to the JSON file where the track is saved.")
    logging.debug(f"track_path = {str(track_path)}")

    # Load the cars and track.
    try:
        cars = read_json_file(car_path)
    except FileNotFoundError:
        logging.critical("car_path file does not exist! Exiting.")
        sys.exit(-1)
    except json.JSONDecodeError as jde:
        logging.critical("car_path file could not be parsed as JSON! Exiting.")
        logging.error(jde.msg)
        sys.exit(-1)
    
    try:
        track = read_json_file(track_path)
    except FileNotFoundError:
        logging.critical("track_path file does not exist! Exiting.")
        sys.exit(-1)
    except json.JSONDecodeError as jde:
        logging.critical("track_path file could not be parsed as JSON! Exiting.")
        logging.error(jde.msg)
        sys.exit(-1)

    # Get the number of laps to run.
    continue_check = False
    while not continue_check:
        try:
            logging.info("Fetching number of laps from user.")
            user_input = input("Please type the number of laps you'd like to race.")
            num_laps = int(user_input)
            logging.debug(f"User put in {str(num_laps)} as integer input.")
        except ValueError:
            logging.info("User put in a value that was not parsable as an integer.")
            logging.debug(f"User input: {user_input}")
            print("Please try again. Only insert whole integer numbers.")
            continue
        
        # Estimate a race time.
        lap_time_estimate = 0
        logging.info("Estimating lap time.")
        for item_id in track["items"].keys():
            logging.debug(f"Track item {str(item_id)} base_time: {str(track['items'][item_id]['base_time'])}")
            lap_time_estimate += track["items"][item_id]["base_time"]
            logging.debug(f"Total time so far: {str(lap_time_estimate)}")
        lap_time_estimate *= num_laps
        logging.info(f"Total race estimate: {str(lap_time_estimate)}")

        is_good = input(f"The estimated race time is {str(lap_time_estimate / 60.0)} minutes long.\nWould you like to continue with this time? (yes/no)")
        logging.debug(f"User input for confirmation: {is_good}")
        if "yes" in is_good.lower():
            continue_check = True
            print(f"Continuing with {str(num_laps)} laps.")
            logging.info(f"User confirmed number of laps at {str(num_laps)}")
        else:
            logging.info(f"User denied number of laps at {str(num_laps)}")

    # Run the race weekend.
    logging.info(f"Running race weekend.")

    print("Let's go down to the track now, live with Kerbin World News' World of Sports!")
    race_results = run_race_weekend(cars, track, num_laps)

    print("Wow, that was an exciting race! Let's go to the results now.")
    for car in race_results:
        print(f"\tCar #: {car['car_number']}")
        print(f"\t\tDriver: {car['driver_name']}")
        print(f"\t\tTeam: {car['team_name']}")
        print(f"\t\tRemaining health: {car['health']}")
        print(f"\t\tPosition: {car['position']}")
        print(f"\t\tRace time: {car['race_time']}")
    print("Incredible! Now for the race statistics.")
    print(f"\tSuccessful passes: {successful_passes}")
    print(f"\tUnsuccessful passes: {unsuccessful_passes}")
    print(f"\tLead changes: {lead_changes}")
    print(f"\tCrashes: {crashes}")
    print(f"\tRetirements: {retirements}")
    logging.info("Race results:\n" + str(race_results))


if __name__ == "__main__":
    main()
